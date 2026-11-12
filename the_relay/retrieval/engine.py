"""
Hybrid Retrieval Engine for The Relay.
Supports:
- BM25Okapi (lexical matching)
- Dense semantic vector search (cosine similarity on normalized embeddings)
- Reciprocal Rank Fusion (RRF) combining BM25 and Dense rankings
- On-disk vector caching with content/model invalidation
- Configurable retrieval modes (bm25_only, dense_only, hybrid)
- Diagnostics mode exposing rank breakdowns and metadata boosts
"""
import re
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np
from rank_bm25 import BM25Okapi

from the_relay.config import RETRIEVAL_SETTINGS, DEFAULT_SETTING
from the_relay.ingestion.parser import StructuredDocument, parse_all_papers
from the_relay.retrieval.chunker import Chunk, build_chunk_indices
from the_relay.retrieval.embeddings import (
    BaseEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    DeterministicMockEmbeddingProvider,
    EmbeddingCache
)

logger = logging.getLogger(__name__)

@dataclass
class RetrievalDiagnostics:
    query: str
    setting_key: str
    effective_setting: str
    requested_mode: str
    effective_mode: str
    top_k: int
    bm25_rankings: list[dict[str, Any]] = field(default_factory=list)
    dense_rankings: list[dict[str, Any]] = field(default_factory=list)
    fused_rankings: list[dict[str, Any]] = field(default_factory=list)
    selected_chunks: list[Chunk] = field(default_factory=list)
    cache_hit: bool = False

class RetrievalEngine:
    def __init__(
        self,
        docs: Optional[dict[str, StructuredDocument]] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        cache: Optional[EmbeddingCache] = None,
        use_mock_embeddings: bool = False,
        mock_embedding_dim: int = 64
    ):
        self.docs = docs or parse_all_papers()
        self.cache = cache or EmbeddingCache()

        # Select embedding provider: mock if requested, otherwise production SentenceTransformer
        if embedding_provider:
            self.embedding_provider = embedding_provider
        elif use_mock_embeddings:
            self.embedding_provider = DeterministicMockEmbeddingProvider(dimension=mock_embedding_dim)
        else:
            self.embedding_provider = SentenceTransformerEmbeddingProvider()

        self._indices: dict[str, list[Chunk]] = {}
        self._bm25_models: dict[str, BM25Okapi] = {}
        self._tokenized_corpus: dict[str, list[list[str]]] = {}
        self._dense_embeddings: dict[str, np.ndarray] = {}
        self._cache_hits: dict[str, bool] = {}

        # Build indices for all configured settings
        for setting_key, conf in RETRIEVAL_SETTINGS.items():
            self._build_setting_index(setting_key, conf["piece_size"])

    def _tokenize(self, text: str) -> list[str]:
        """Simple lowercase word tokenizer for BM25."""
        return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())

    def _build_setting_index(self, setting_key: str, piece_size: int):
        """Index chunks for BM25 and precompute / load cached dense embeddings."""
        chunks = build_chunk_indices(self.docs, target_tokens=piece_size)
        self._indices[setting_key] = chunks

        # 1. BM25 Index
        tokenized = [self._tokenize(f"{c.paper_title} {c.section} {c.text}") for c in chunks]
        self._tokenized_corpus[setting_key] = tokenized
        self._bm25_models[setting_key] = BM25Okapi(tokenized)

        # 2. Dense Embeddings Index with Cache Invalidation
        chunk_ids = [c.chunk_id for c in chunks]
        content_hashes = [hashlib.sha256(c.text.encode("utf-8")).hexdigest() for c in chunks]

        cache_key = self.cache.compute_cache_key(
            setting_key=setting_key,
            model_name=self.embedding_provider.model_name,
            model_version=self.embedding_provider.model_version,
            chunk_ids=chunk_ids,
            content_hashes=content_hashes
        )

        cached_vecs = self.cache.get(cache_key)
        if cached_vecs is not None and len(cached_vecs) == len(chunks):
            self._dense_embeddings[setting_key] = cached_vecs
            self._cache_hits[setting_key] = True
        else:
            # Generate and cache embeddings
            doc_texts = [f"{c.paper_title}. {c.section}: {c.text}" for c in chunks]
            vecs = self.embedding_provider.embed_documents(doc_texts)
            self._dense_embeddings[setting_key] = vecs
            self.cache.put(cache_key, vecs, chunk_ids)
            self._cache_hits[setting_key] = False

    def retrieve(
        self,
        query: str,
        setting_key: str = DEFAULT_SETTING,
        limit_warning: bool = False,
        target_paper_hint: Optional[str] = None,
        mode: Optional[str] = None,
        diagnostics: bool = False
    ) -> Any:
        """
        Retrieve relevant research paper passages.
        Supports modes: 'bm25_only', 'dense_only', 'hybrid', or None (uses setting default).
        If limit_warning is True, falls back to setting_a.
        Returns:
            (selected_chunks, effective_setting) if diagnostics is False
            (selected_chunks, effective_setting, diagnostics_obj) if diagnostics is True
        """
        effective_setting = "setting_a" if limit_warning else setting_key
        conf = RETRIEVAL_SETTINGS.get(effective_setting, RETRIEVAL_SETTINGS["setting_b"])
        top_k = conf["pieces_fetched"]
        requested_mode = mode or conf.get("mode", "hybrid")

        chunks = self._indices[effective_setting]
        bm25 = self._bm25_models[effective_setting]
        doc_embeddings = self._dense_embeddings[effective_setting]
        n_docs = len(chunks)

        q_tokens = self._tokenize(query)
        if not q_tokens or n_docs == 0:
            if diagnostics:
                diag = RetrievalDiagnostics(
                    query=query,
                    setting_key=setting_key,
                    effective_setting=effective_setting,
                    requested_mode=requested_mode,
                    effective_mode=requested_mode,
                    top_k=top_k
                )
                return [], effective_setting, diag
            return [], effective_setting

        # 1. Compute BM25 scores and ranks
        bm25_raw_scores = bm25.get_scores(q_tokens)
        bm25_sorted_indices = np.argsort(-bm25_raw_scores)
        bm25_ranks = np.zeros(n_docs, dtype=int)
        for rank, idx in enumerate(bm25_sorted_indices, 1):
            bm25_ranks[idx] = rank

        # 2. Compute Dense vector cosine similarity and ranks
        effective_mode = requested_mode
        dense_scores = np.zeros(n_docs, dtype=np.float32)
        dense_ranks = np.zeros(n_docs, dtype=int)

        if requested_mode in ("dense_only", "hybrid"):
            try:
                q_vec = self.embedding_provider.embed_query(query)
                # Normalized dot product = cosine similarity
                dense_scores = np.dot(doc_embeddings, q_vec)
                dense_sorted_indices = np.argsort(-dense_scores)
                for rank, idx in enumerate(dense_sorted_indices, 1):
                    dense_ranks[idx] = rank
            except Exception as e:
                logger.warning(f"Dense embedding failed ({e}); downgrading to bm25_only.")
                effective_mode = "bm25_only"

        # 3. Combine Rankings / Scoring
        # RRF Parameter k=60
        rrf_k = 60.0
        final_scores = np.zeros(n_docs, dtype=np.float32)

        if effective_mode == "bm25_only":
            final_scores = bm25_raw_scores.copy()
        elif effective_mode == "dense_only":
            final_scores = dense_scores.copy()
        else:
            # True Hybrid: Reciprocal Rank Fusion (RRF)
            # RRF_Score = 1.0 / (k + rank_bm25) + 1.0 / (k + rank_dense)
            for i in range(n_docs):
                rrf_bm25 = 1.0 / (rrf_k + bm25_ranks[i])
                rrf_dense = 1.0 / (rrf_k + dense_ranks[i])
                final_scores[i] = rrf_bm25 + rrf_dense

        # 4. Optional Metadata Boosts (Multiplicative adjustment, preserving raw ranks)
        metadata_boosts_applied = []
        if conf.get("rerank", False):
            for i in range(n_docs):
                chunk = chunks[i]
                sec_lower = chunk.section.lower()
                title_lower = chunk.paper_title.lower()
                boost_pct = 0.0

                # Section heading alignment (+15%)
                if any(token in sec_lower for token in q_tokens):
                    boost_pct += 0.15

                # Paper title token alignment (+10%)
                if any(token in title_lower for token in q_tokens):
                    boost_pct += 0.10

                # Target paper hint (+30%)
                if target_paper_hint and target_paper_hint.lower() in title_lower:
                    boost_pct += 0.30

                if boost_pct > 0.0:
                    final_scores[i] *= (1.0 + boost_pct)
                    metadata_boosts_applied.append({
                        "chunk_id": chunk.chunk_id,
                        "boost_pct": round(boost_pct * 100.0, 1)
                    })

        # 5. Sort descending and pick top_k
        final_sorted_indices = np.argsort(-final_scores)
        selected_indices = [
            idx for idx in final_sorted_indices[:top_k]
            if final_scores[idx] > 0.0
        ]
        selected_chunks = [chunks[i] for i in selected_indices]

        if diagnostics:
            bm25_top = [
                {"rank": rank, "chunk_id": chunks[idx].chunk_id, "score": round(float(bm25_raw_scores[idx]), 3)}
                for rank, idx in enumerate(bm25_sorted_indices[:top_k], 1)
            ]
            dense_top = [
                {"rank": rank, "chunk_id": chunks[idx].chunk_id, "cosine_sim": round(float(dense_scores[idx]), 3)}
                for rank, idx in enumerate(np.argsort(-dense_scores)[:top_k], 1)
            ] if effective_mode != "bm25_only" else []
            fused_top = [
                {"rank": rank, "chunk_id": chunks[idx].chunk_id, "final_score": round(float(final_scores[idx]), 5)}
                for rank, idx in enumerate(final_sorted_indices[:top_k], 1)
            ]
            diag = RetrievalDiagnostics(
                query=query,
                setting_key=setting_key,
                effective_setting=effective_setting,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                top_k=top_k,
                bm25_rankings=bm25_top,
                dense_rankings=dense_top,
                fused_rankings=fused_top,
                selected_chunks=selected_chunks,
                cache_hit=self._cache_hits.get(effective_setting, False)
            )
            return selected_chunks, effective_setting, diag

        return selected_chunks, effective_setting

    def format_context_prompt(self, chunks: list[Chunk]) -> str:
        """Format retrieved passages into a structured reference context preserving chunk-level provenance."""
        if not chunks:
            return "No relevant passages found in the library."

        parts = []
        for i, c in enumerate(chunks, 1):
            parts.append(
                f"--- Reference Passage [{i}] (Chunk ID: {c.chunk_id}) ---\n"
                f"Paper: {c.paper_title} ({c.paper_id})\n"
                f"Location: Page {c.page_number}, Section: {c.section}\n"
                f"Content:\n{c.text}\n"
            )
        return "\n".join(parts)
