"""
Information Retrieval (IR) metrics computation: Recall@K, Precision@K, MRR, and nDCG@K.
Evaluates passage retrieval quality against verified ground truth evidence annotations.
"""
import math
from typing import Any, Optional
from the_relay.retrieval.chunker import Chunk

def compute_recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Recall@K = |Retrieved@K ∩ Relevant| / |Relevant|
    Denominator: Total number of relevant documents for this query.
    """
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = len(set(top_k) & relevant_ids)
    return hits / len(relevant_ids)

def compute_precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Precision@K = |Retrieved@K ∩ Relevant| / K
    Denominator: K (number of passages fetched).
    """
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = len(set(top_k) & relevant_ids)
    return hits / k

def compute_mrr(retrieved_ids: list[str], relevant_ids: set[str], k: Optional[int] = None) -> float:
    """
    Mean Reciprocal Rank (MRR) for a single query.
    MRR = 1 / rank of first relevant passage (1-indexed), or 0.0 if not found in top-K.
    """
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k] if k is not None else retrieved_ids
    for rank, doc_id in enumerate(top_k, 1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0

def compute_ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain at rank K (nDCG@K).
    Binary relevance: 1 if doc in relevant_ids, else 0.
    DCG@K = sum_{i=1}^K rel_i / log2(i + 1)
    IDCG@K = sum_{i=1}^{min(K, |relevant|)} 1.0 / log2(i + 1)
    """
    if not relevant_ids or k <= 0:
        return 0.0

    top_k = retrieved_ids[:k]
    dcg = 0.0
    for i, doc_id in enumerate(top_k, 1):
        rel = 1.0 if doc_id in relevant_ids else 0.0
        if rel > 0.0:
            dcg += rel / math.log2(i + 1)

    idcg_limit = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, idcg_limit + 1))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg

def evaluate_retrieval_query(
    retrieved_chunks: list[Chunk],
    relevant_paper_id: str,
    relevant_pages: set[int],
    k: int
) -> dict[str, Any]:
    """
    Evaluate retrieval quality for a single query given relevant paper and pages.
    A chunk is considered relevant if it matches the target paper and one of the relevant pages.
    """
    retrieved_ids = [c.chunk_id for c in retrieved_chunks]

    # Identify which retrieved chunks are relevant
    relevant_retrieved = {
        c.chunk_id for c in retrieved_chunks
        if c.paper_id == relevant_paper_id and c.page_number in relevant_pages
    }

    # Effective relevant set size (at least 1 for valid evaluation)
    denom_relevant_count = max(1, len(relevant_pages))

    top_k_ids = retrieved_ids[:k]
    hits = len(set(top_k_ids) & relevant_retrieved)
    recall = hits / denom_relevant_count
    precision = hits / k if k > 0 else 0.0

    mrr = 0.0
    for rank, doc_id in enumerate(top_k_ids, 1):
        if doc_id in relevant_retrieved:
            mrr = 1.0 / rank
            break

    dcg = 0.0
    for i, doc_id in enumerate(top_k_ids, 1):
        if doc_id in relevant_retrieved:
            dcg += 1.0 / math.log2(i + 1)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, denom_relevant_count) + 1))
    ndcg = (dcg / idcg) if idcg > 0.0 else 0.0

    return {
        "k": k,
        "hits": hits,
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg, 4),
        "denominators": {
            "retrieved_k": k,
            "relevant_target_pages": denom_relevant_count
        }
    }
