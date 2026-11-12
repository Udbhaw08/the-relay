# Phase 4 Implementation Report: True Hybrid Retrieval (BM25 + Dense Embeddings + Rank Fusion)

**Date:** 2026-11-12<br>
**Branch:** `feat/the-relay-groq-hardening`<br>
**Phase Status:** COMPLETED<br>
**Test Suite:** 71 passed / 0 failed (12 dedicated retrieval tests in `tests/test_retrieval.py`)

---

## 1. Executive Summary & Objective

In Phase 4, we upgraded the retrieval pipeline from a purely lexical BM25 mechanism with ad-hoc additive boosts to a **true hybrid semantic retriever** integrating:
1. **Lexical Matching:** Standalone `BM25Okapi` mode (`bm25_only`).
2. **Dense Semantic Retrieval:** Normalized vector embeddings (`dense_only`) with cosine similarity:
   $$\text{sim}(q, d) = q \cdot d$$
   using `sentence-transformers==3.4.1` with production model `all-MiniLM-L6-v2` (384-dimensional normalized vectors).
3. **Reciprocal Rank Fusion (RRF):** Combining BM25 and Dense ranks deterministically:
   $$\text{RRF}(d) = \frac{1.0}{k + r_{\text{bm25}}(d)} + \frac{1.0}{k + r_{\text{dense}}(d)}$$
   with standard constant $k = 60.0$, eliminating uncalibrated score additions.
4. **On-Disk Embedding Cache:** Storing precomputed chunk embeddings in `data/cache/embeddings/` keyed by cryptographic SHA-256 hashes of model name, model version, chunk IDs, and chunk text content. Modifying chunk text automatically invalidates stale caches.
5. **Fast Offline Deterministic Testing:** Implementing `DeterministicMockEmbeddingProvider` (64-dimensional hash unit vectors) ensuring fast, repeatable unit tests without requiring network downloads.
6. **Explicit Modes and Downgrade Transparency:** Defining explicit retrieval modes (`bm25_only`, `dense_only`, `hybrid`). If dense embeddings are unavailable, the engine explicitly downgrades to `bm25_only` and records `effective_mode = "bm25_only"`, preventing BM25 from ever being falsely labeled as hybrid.
7. **Diagnostics Mode & IR Evaluation Metrics:** Full breakdown of BM25 ranks, Dense cosine similarities, fused scores, and applied boosts, alongside standard IR metrics (Recall@K, Precision@K, MRR, nDCG@K).

---

## 2. Key Architectural Modules

### 2.1 Embedding Providers & Cache (`the_relay/retrieval/embeddings.py`)
Implemented in [`the_relay/retrieval/embeddings.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/retrieval/embeddings.py):
- `BaseEmbeddingProvider`: Abstract interface for query and document vector encoding.
- `SentenceTransformerEmbeddingProvider`: Production dense encoder utilizing `all-MiniLM-L6-v2`, lazy model initialization, and `normalize_embeddings = True`.
- `DeterministicMockEmbeddingProvider`: Fast offline pseudo-vector encoder based on token SHA-256 hash buckets, used for deterministic test execution.
- `EmbeddingCache`: Manages compressed `.npz` vector arrays keyed by `sha256(setting_key:model:version:chunk_ids:content_hashes)`.

### 2.2 Hybrid Retrieval Engine (`the_relay/retrieval/engine.py`)
Implemented in [`the_relay/retrieval/engine.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/retrieval/engine.py):
- `retrieve(query, setting_key, limit_warning, target_paper_hint, mode, diagnostics)`:
  - Supports explicit `mode` selection: `bm25_only`, `dense_only`, `hybrid`.
  - Computes raw BM25 scores and ranks: $r_{\text{bm25}} \in [1, N]$.
  - Computes dense cosine similarities and ranks: $r_{\text{dense}} \in [1, N]$.
  - Fuses via RRF ($k=60.0$) when in `hybrid` mode.
  - Multiplicative metadata boosts (+15% section heading match, +10% title match, +30% paper hint) are applied as scaling factors on candidate ranks, preserving raw rank transparency.
  - `diagnostics=True` returns `RetrievalDiagnostics` with full top-K candidate breakdowns for BM25, Dense, Fused, and metadata adjustments.

### 2.3 Information Retrieval Metrics (`the_relay/retrieval/metrics.py`)
Implemented in [`the_relay/retrieval/metrics.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/retrieval/metrics.py):
- `compute_recall_at_k`: $|\text{Retrieved@K} \cap \text{Relevant}| / |\text{Relevant}|$.
- `compute_precision_at_k`: $|\text{Retrieved@K} \cap \text{Relevant}| / K$.
- `compute_mrr`: Reciprocal rank of the first relevant passage.
- `compute_ndcg_at_k`: Normalized discounted cumulative gain against ideal DCG.
- `evaluate_retrieval_query`: Evaluates retrieved passages against ground-truth paper ID and page numbers.

### 2.4 Configuration Alignment (`the_relay/config.py`)
Updated [`the_relay/config.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/config.py):
- `setting_a`: `mode = "bm25_only"`, piece size 250, top-3, no re-ranking.
- `setting_b`: `mode = "hybrid"`, piece size 500, top-5, true hybrid (BM25 + Dense + RRF).
- `setting_c`: `mode = "hybrid"`, piece size 1000, top-7, deep hybrid (BM25 + Dense + RRF).

---

## 3. Retrieval Modes & Settings Comparison

| Retrieval Setting | Piece Size (tokens) | Fetched Pieces | Retrieval Mode | Re-ranking & Boosts | Primary Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Setting A** | 250 (~1,000 chars) | Top-3 | `bm25_only` | None | Low latency, minimal context token overhead, rate-limit fallback |
| **Setting B** | 500 (~2,000 chars) | Top-5 | `hybrid` (BM25 + Dense + RRF) | Section & Paper Boosts | Balanced production setting, high precision and recall |
| **Setting C** | 1,000 (~4,000 chars) | Top-7 | `hybrid` (BM25 + Dense + RRF) | Section & Paper Boosts | Deep research queries, maximum evidence recall |

---

## 4. Verification and Test Results

Dedicated retrieval test suite in [`tests/test_retrieval.py`](file:///c:/Users/udbha/Desktop/aivoice/tests/test_retrieval.py):
1. `test_retrieval_attention_query`: PASSED
2. `test_retrieval_moshi_query`: PASSED
3. `test_retrieval_adaptive_degradation_on_limit_warning`: PASSED
4. `test_explicit_modes_bm25_only`: PASSED
5. `test_explicit_modes_dense_only`: PASSED
6. `test_explicit_modes_hybrid_rrf`: PASSED
7. `test_rrf_rank_fusion_determinism`: PASSED
8. `test_embedding_cache_invalidation_on_content_change`: PASSED
9. `test_explicit_downgrade_when_dense_fails`: PASSED
10. `test_chunk_provenance_preservation`: PASSED
11. `test_retrieval_metrics_calculations`: PASSED
12. `test_evaluate_retrieval_query_helper`: PASSED

Full repository test suite execution:
- Total tests: **71 passed**
- Execution time: ~90.61s
- Failures: **0**

---

## 5. Acceptance Checklist

- [x] Standalone BM25 mode preserved and testable (`bm25_only`).
- [x] Dense vector similarity implemented with normalized embeddings and cosine similarity (`dense_only`).
- [x] True hybrid rank fusion using Reciprocal Rank Fusion (RRF, $k=60.0$) without raw score additions.
- [x] On-disk embedding cache keyed by SHA-256 of model, version, chunk IDs, and content hashes.
- [x] Content changes invalidate stale cached vectors.
- [x] Explicit downgrade to `bm25_only` with logged effective mode if dense encoding fails.
- [x] Diagnostics mode returns complete rank breakdowns for BM25, Dense, Fused, and boosts.
- [x] Information Retrieval metrics (Recall@K, Precision@K, MRR, nDCG@K) implemented and tested.
- [x] All 71 tests passing.
