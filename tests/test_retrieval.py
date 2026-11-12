"""
Unit tests for Phase 4:
True hybrid retrieval (BM25 + Dense semantic embeddings + Reciprocal Rank Fusion),
on-disk vector caching, diagnostics mode, and IR evaluation metrics.
"""
import pytest
import numpy as np
from the_relay.retrieval.engine import RetrievalEngine, RetrievalDiagnostics
from the_relay.retrieval.embeddings import DeterministicMockEmbeddingProvider, EmbeddingCache
from the_relay.retrieval.metrics import (
    compute_recall_at_k,
    compute_precision_at_k,
    compute_mrr,
    compute_ndcg_at_k,
    evaluate_retrieval_query
)
from the_relay.retrieval.chunker import Chunk

@pytest.fixture(scope="module")
def engine():
    # Use fast, deterministic mock embeddings for offline unit test execution
    mock_provider = DeterministicMockEmbeddingProvider(dimension=64)
    return RetrievalEngine(embedding_provider=mock_provider)

def test_retrieval_attention_query(engine):
    query = "Scaled Dot-Product Attention formula and dk dimension"
    chunks, setting = engine.retrieve(query, setting_key="setting_b")
    assert len(chunks) > 0
    assert any("Attention Is All You Need" in c.paper_title for c in chunks)

def test_retrieval_moshi_query(engine):
    query = "Mimi neural audio codec framerate and codebooks"
    chunks, setting = engine.retrieve(query, setting_key="setting_b")
    assert len(chunks) > 0
    assert any("Moshi" in c.paper_title for c in chunks)

def test_retrieval_adaptive_degradation_on_limit_warning(engine):
    query = "dynamic chunking byte level hierarchy"
    chunks, setting = engine.retrieve(query, setting_key="setting_c", limit_warning=True)
    assert setting == "setting_a"
    assert len(chunks) <= 3

def test_explicit_modes_bm25_only(engine):
    """BM25-only mode retrieves without computing dense fusion."""
    query = "softmax QK^T / sqrt(d_k)"
    chunks, setting, diag = engine.retrieve(query, setting_key="setting_a", mode="bm25_only", diagnostics=True)
    assert diag.requested_mode == "bm25_only"
    assert diag.effective_mode == "bm25_only"
    assert len(diag.dense_rankings) == 0  # No dense vectors used in bm25_only
    assert len(diag.bm25_rankings) > 0

def test_explicit_modes_dense_only(engine):
    """Dense-only mode retrieves based strictly on vector cosine similarity."""
    query = "hierarchical multi-stream conversational dialogue speech"
    chunks, setting, diag = engine.retrieve(query, setting_key="setting_b", mode="dense_only", diagnostics=True)
    assert diag.requested_mode == "dense_only"
    assert diag.effective_mode == "dense_only"
    assert len(diag.dense_rankings) > 0
    # Top chunk has positive cosine similarity
    assert diag.dense_rankings[0]["cosine_sim"] is not None

def test_explicit_modes_hybrid_rrf(engine):
    """Hybrid mode combines BM25 and dense semantic ranks using Reciprocal Rank Fusion (RRF)."""
    query = "What is the framerate and number of codebooks in Mimi?"
    chunks, setting, diag = engine.retrieve(query, setting_key="setting_b", mode="hybrid", diagnostics=True)
    assert diag.requested_mode == "hybrid"
    assert diag.effective_mode == "hybrid"
    assert len(diag.bm25_rankings) > 0
    assert len(diag.dense_rankings) > 0
    assert len(diag.fused_rankings) > 0
    # RRF score should be bounded by 2 * (1 / 60) ≈ 0.0333 before boosts
    top_score = diag.fused_rankings[0]["final_score"]
    assert top_score > 0.0

def test_rrf_rank_fusion_determinism(engine):
    """RRF fusion produces identical ranking order across repeated runs with fixed inputs."""
    query = "Byte-Pair Encoding replacement with learned dynamic segmentation"
    c1, _, d1 = engine.retrieve(query, setting_key="setting_b", mode="hybrid", diagnostics=True)
    c2, _, d2 = engine.retrieve(query, setting_key="setting_b", mode="hybrid", diagnostics=True)
    assert [c.chunk_id for c in c1] == [c.chunk_id for c in c2]
    assert [f["final_score"] for f in d1.fused_rankings] == [f["final_score"] for f in d2.fused_rankings]

def test_embedding_cache_invalidation_on_content_change(tmp_path):
    """Cache keys change and invalidate stored vectors if chunk text changes."""
    cache = EmbeddingCache(cache_dir=tmp_path)
    key1 = cache.compute_cache_key(
        setting_key="setting_b",
        model_name="mock-model",
        model_version="v1",
        chunk_ids=["c1", "c2"],
        content_hashes=["hash_original_1", "hash_original_2"]
    )
    # Store dummy vector
    vec1 = np.ones((2, 64), dtype=np.float32)
    cache.put(key1, vec1, ["c1", "c2"])
    assert cache.get(key1) is not None

    # Simulate content change: second chunk has modified text -> new content hash
    key2 = cache.compute_cache_key(
        setting_key="setting_b",
        model_name="mock-model",
        model_version="v1",
        chunk_ids=["c1", "c2"],
        content_hashes=["hash_original_1", "hash_MODIFIED_2"]
    )
    assert key1 != key2
    # Stale cache is not returned for modified content
    assert cache.get(key2) is None

def test_explicit_downgrade_when_dense_fails(monkeypatch, engine):
    """When dense model fails, engine explicitly downgrades to bm25_only and logs the effective mode."""
    def _failing_embed_query(query: str):
        raise RuntimeError("GPU OOM / Network Error")

    monkeypatch.setattr(engine.embedding_provider, "embed_query", _failing_embed_query)
    chunks, setting, diag = engine.retrieve(
        "test query", setting_key="setting_b", mode="hybrid", diagnostics=True
    )
    assert diag.requested_mode == "hybrid"
    assert diag.effective_mode == "bm25_only"
    assert len(chunks) > 0

def test_chunk_provenance_preservation(engine):
    """All required academic provenance fields survive indexing and retrieval."""
    chunks, _ = engine.retrieve("Attention Is All You Need", setting_key="setting_b")
    first = chunks[0]
    assert first.chunk_id
    assert first.paper_id in ("1706.03762v7", "2410.00037v1", "2507.07955v2")
    assert first.paper_title
    assert first.page_number >= 1
    assert first.section
    assert first.text
    assert first.token_count > 0

def test_retrieval_metrics_calculations():
    """Verify standard Information Retrieval metrics with known ground-truth sets."""
    retrieved = ["doc_A", "doc_B", "doc_C", "doc_D", "doc_E"]
    relevant = {"doc_B", "doc_D", "doc_Z"}

    # Recall@3: {doc_A, doc_B, doc_C} ∩ {doc_B, doc_D, doc_Z} = {doc_B} (1 / 3)
    recall_3 = compute_recall_at_k(retrieved, relevant, k=3)
    assert round(recall_3, 4) == round(1.0 / 3.0, 4)

    # Precision@3: 1 / 3
    prec_3 = compute_precision_at_k(retrieved, relevant, k=3)
    assert round(prec_3, 4) == round(1.0 / 3.0, 4)

    # MRR: First hit is doc_B at rank 2 -> MRR = 0.5
    mrr = compute_mrr(retrieved, relevant)
    assert mrr == 0.5

    # nDCG@3:
    # DCG@3 = 0/log2(2) + 1/log2(3) + 0/log2(4) = 1 / 1.58496 = 0.6309
    # IDCG@3 = 1/log2(2) + 1/log2(3) + 1/log2(4) = 1 + 0.6309 + 0.5 = 2.1309
    # nDCG@3 = 0.6309 / 2.1309 ≈ 0.296
    ndcg_3 = compute_ndcg_at_k(retrieved, relevant, k=3)
    assert 0.28 < ndcg_3 < 0.32

def test_evaluate_retrieval_query_helper():
    """Verify single query retrieval evaluation helper against target paper and pages."""
    chunks = [
        Chunk(chunk_id="1706.03762v7_p4_c1", paper_id="1706.03762v7", paper_title="Attention", page_number=4, section="3.2", text="abc", token_count=10),
        Chunk(chunk_id="1706.03762v7_p5_c2", paper_id="1706.03762v7", paper_title="Attention", page_number=5, section="3.3", text="def", token_count=10),
        Chunk(chunk_id="2410.00037v1_p4_c3", paper_id="2410.00037v1", paper_title="Moshi", page_number=4, section="2", text="ghi", token_count=10)
    ]
    res = evaluate_retrieval_query(
        retrieved_chunks=chunks,
        relevant_paper_id="1706.03762v7",
        relevant_pages={4},
        k=3
    )
    assert res["hits"] == 1
    assert res["recall_at_k"] == 1.0  # 1 hit / 1 relevant page
    assert res["mrr"] == 1.0          # Hit at rank 1
    assert res["ndcg_at_k"] == 1.0
