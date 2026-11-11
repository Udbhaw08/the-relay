"""Hybrid retrieval engine with dynamic setting switching and resilience fallbacks."""
import re
from typing import Optional
from rank_bm25 import BM25Okapi
from the_relay.config import RETRIEVAL_SETTINGS, DEFAULT_SETTING
from the_relay.ingestion.parser import StructuredDocument, parse_all_papers
from the_relay.retrieval.chunker import Chunk, build_chunk_indices, estimate_tokens

class RetrievalEngine:
    def __init__(self, docs: Optional[dict[str, StructuredDocument]] = None):
        self.docs = docs or parse_all_papers()
        self._indices: dict[str, list[Chunk]] = {}
        self._bm25_models: dict[str, BM25Okapi] = {}
        self._tokenized_corpus: dict[str, list[list[str]]] = {}
        
        # Build indexes for each setting
        for setting_key, conf in RETRIEVAL_SETTINGS.items():
            self._build_setting_index(setting_key, conf["piece_size"])

    def _tokenize(self, text: str) -> list[str]:
        """Simple lowercase word tokenizer."""
        return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())

    def _build_setting_index(self, setting_key: str, piece_size: int):
        chunks = build_chunk_indices(self.docs, target_tokens=piece_size)
        self._indices[setting_key] = chunks
        tokenized = [self._tokenize(f"{c.paper_title} {c.section} {c.text}") for c in chunks]
        self._tokenized_corpus[setting_key] = tokenized
        self._bm25_models[setting_key] = BM25Okapi(tokenized)

    def retrieve(
        self,
        query: str,
        setting_key: str = DEFAULT_SETTING,
        limit_warning: bool = False,
        target_paper_hint: Optional[str] = None
    ) -> tuple[list[Chunk], str]:
        """
        Retrieve relevant paper passages.
        If limit_warning is True, falls back to setting_a (fewer chunks/tokens).
        Returns (chunks, effective_setting_name).
        """
        # Adaptive degradation when rate limit is close
        effective_setting = "setting_a" if limit_warning else setting_key
        conf = RETRIEVAL_SETTINGS.get(effective_setting, RETRIEVAL_SETTINGS["setting_b"])
        
        chunks = self._indices[effective_setting]
        bm25 = self._bm25_models[effective_setting]
        
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return [], effective_setting

        bm25_scores = bm25.get_scores(q_tokens)
        
        # Candidate ranking
        scored_candidates: list[tuple[float, Chunk]] = []
        for i, score in enumerate(bm25_scores):
            chunk = chunks[i]
            final_score = float(score)
            
            # Re-ranking logic if enabled
            if conf["rerank"]:
                # Section heading alignment bonus
                sec_lower = chunk.section.lower()
                title_lower = chunk.paper_title.lower()
                for token in q_tokens:
                    if token in sec_lower:
                        final_score += 1.5
                    if token in title_lower:
                        final_score += 1.0
                
                # Paper hint bias
                if target_paper_hint and target_paper_hint.lower() in title_lower:
                    final_score += 3.0

            scored_candidates.append((final_score, chunk))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Filter top-k
        top_k = conf["pieces_fetched"]
        selected_chunks = [c for s, c in scored_candidates[:top_k] if s > 0.0]
        
        return selected_chunks, effective_setting

    def format_context_prompt(self, chunks: list[Chunk]) -> str:
        """Format retrieved passages into a structured reference context for LLM."""
        if not chunks:
            return "No relevant passages found in the library."

        parts = []
        for i, c in enumerate(chunks, 1):
            parts.append(
                f"--- Reference Passage [{i}] ---\n"
                f"Paper: {c.paper_title} ({c.paper_id})\n"
                f"Location: Page {c.page_number}, Section: {c.section}\n"
                f"Content:\n{c.text}\n"
            )
        return "\n".join(parts)

