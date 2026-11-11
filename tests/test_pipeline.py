"""Unit tests for the 4-step pipeline and resilience logic."""
from the_relay.pipeline.orchestrator import RelayPipeline

def test_pipeline_4_steps_and_citations():
    pipeline = RelayPipeline()
    res = pipeline.run_request(
        query="What is the formula for multi-head attention?",
        request_id="test_pipe_01",
        source="stand-in",
        retrieval_setting="setting_b"
    )
    assert res.status == "ok"
    assert "Step 1: Query Parser" in res.steps_executed
    assert "Step 2: Passage Retrieval Tool" in res.steps_executed
    assert "Step 3: Synthesis & Citation" in res.steps_executed
    assert "Step 4: Verification Guard" in res.steps_executed
    assert len(res.citations_found) > 0
    assert res.answer_grade == "correct"

def test_pipeline_unanswerable_refusal():
    pipeline = RelayPipeline()
    res = pipeline.run_request(
        query="What are the proprietary patient IDs in Cartesia clinical deployment?",
        request_id="test_pipe_02",
        source="stand-in",
        expected_negative=True
    )
    assert res.status == "ok"
    assert res.answer_grade == "refused_correctly"
    assert "do not" in res.answer.lower()
