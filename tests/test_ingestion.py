"""Unit tests for ingestion and chunking."""
import pytest
from the_relay.config import REQUIRED_PAPERS, PAPERS_DIR
from the_relay.ingestion.parser import parse_paper_pdf
from the_relay.retrieval.chunker import chunk_document, estimate_tokens

def test_paper_files_exist():
    for arxiv_id, meta in REQUIRED_PAPERS.items():
        p = PAPERS_DIR / meta["filename"]
        assert p.exists(), f"Paper {p} missing"
        assert p.stat().st_size > 10000

def test_parse_attention_paper():
    p = PAPERS_DIR / REQUIRED_PAPERS["1706.03762v7"]["filename"]
    doc = parse_paper_pdf(p, "1706.03762v7")
    assert len(doc.pages) >= 10
    assert "Transformer" in doc.full_text or "Attention" in doc.full_text

def test_chunking_settings():
    p = PAPERS_DIR / REQUIRED_PAPERS["1706.03762v7"]["filename"]
    doc = parse_paper_pdf(p, "1706.03762v7")
    chunks_250 = chunk_document(doc, target_tokens=250)
    chunks_500 = chunk_document(doc, target_tokens=500)
    assert len(chunks_250) > len(chunks_500)
    assert chunks_250[0].token_count <= 400

