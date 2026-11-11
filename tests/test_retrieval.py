"""Unit tests for the hybrid retrieval engine."""
import pytest
from the_relay.retrieval.engine import RetrievalEngine

@pytest.fixture(scope="module")
def engine():
    return RetrievalEngine()

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
    # When limit_warning is True, should degrade to setting_a
    assert setting == "setting_a"
    assert len(chunks) <= 3

