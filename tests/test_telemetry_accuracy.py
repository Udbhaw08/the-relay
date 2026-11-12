"""
Unit and integration tests for Phase 5: Accurate Latency, TTFT, Token, Queue, and Cost Telemetry.
Verifies:
- Null TTFT on failures, rate limits, timeouts, and empty generations.
- Monotonic clock usage and non-negative component duration tracking.
- Queue depth vs in-flight concurrency separation.
- Provider token usage vs heuristic estimates separation.
- Removal of hardcoded cost claims ($0.00).
- Percentile calculation correctness over valid successful samples.
- Simulator vs live-provider provenance labeling.
"""
import pytest
from unittest.mock import MagicMock
import httpx
import groq
import pandas as pd

from the_relay.models.base import ModelResponse
from the_relay.models.stand_in import StandInModelClient
from the_relay.models.groq_client import GroqClient
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult
from the_relay.traffic.generator import ConcurrencyTracker
from the_relay.traffic.logger import ResultsLogger, CSV_COLUMNS
from the_relay.traffic.schema import validate_results_dataframe
from scripts.compute_tables import (
    compute_percentiles,
    format_latencies_3,
    format_latencies_2,
    generate_table_2a_and_2b,
    generate_table_3
)

# 1. Null TTFT on failure, rate-limits, and timeouts
def test_null_ttft_on_stand_in_failures():
    # Rate limited
    client = StandInModelClient(rpm_limit=1, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    resp1 = client.generate("Hello")
    assert resp1.status == "ok"
    assert resp1.first_token_ms is not None

    resp2 = client.generate("World")
    assert resp2.status == "rate_limited"
    assert resp2.first_token_ms is None, "Rate-limited response must have null first_token_ms"
    assert resp2.tokens_out == 0

    # Daily budget exhausted
    client.exhaust_daily_budget()
    resp3 = client.generate("Exhausted")
    assert resp3.status == "rate_limited"
    assert resp3.first_token_ms is None, "Daily budget exhausted response must have null first_token_ms"

    # Simulated timeout
    timeout_client = StandInModelClient(timeout_rate=1.0, failure_rate=0.0, fast_mode=True)
    resp_timeout = timeout_client.generate("Hang")
    assert resp_timeout.status == "timeout"
    assert resp_timeout.first_token_ms is None, "Timeout response must have null first_token_ms"

    # Simulated error
    error_client = StandInModelClient(timeout_rate=0.0, failure_rate=1.0, fast_mode=True)
    resp_err = error_client.generate("Crash")
    assert resp_err.status == "error"
    assert resp_err.first_token_ms is None, "Server error response must have null first_token_ms"

def test_null_ttft_on_groq_failures():
    mock_groq = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")

    # 429 RateLimitError
    resp_429 = httpx.Response(429, request=req, headers={"retry-after": "5", "x-ratelimit-remaining-requests": "0"})
    mock_groq.chat.completions.with_raw_response.create.side_effect = groq.RateLimitError(
        "Rate limit reached", response=resp_429, body={"error": "rate_limit_exceeded"}
    )
    client = GroqClient(api_key="gsk_dummy_test_key", client=mock_groq)
    res = client.generate("Prompt")
    assert res.status == "rate_limited"
    assert res.first_token_ms is None, "Groq rate limit response must have null first_token_ms"

    # 401 AuthenticationError
    resp_401 = httpx.Response(401, request=req, headers={})
    mock_groq.chat.completions.with_raw_response.create.side_effect = groq.AuthenticationError(
        "Invalid key", response=resp_401, body={}
    )
    res_auth = client.generate("Prompt")
    assert res_auth.status == "error"
    assert res_auth.first_token_ms is None, "Groq 401 response must have null first_token_ms"

    # Timeout
    mock_groq.chat.completions.with_raw_response.create.side_effect = groq.APITimeoutError(request=req)
    res_timeout = client.generate("Prompt")
    assert res_timeout.status == "timeout"
    assert res_timeout.first_token_ms is None, "Groq timeout response must have null first_token_ms"

def test_streaming_null_ttft_when_no_text_chunks_yielded():
    mock_groq = MagicMock()
    # Stream returns chunk with no content
    empty_chunk = MagicMock()
    empty_chunk.choices = [MagicMock(delta=MagicMock(content=""))]
    empty_chunk.usage = None
    empty_chunk.id = "chunk_empty"
    mock_groq.chat.completions.create.return_value = [empty_chunk]

    client = GroqClient(api_key="gsk_dummy_test_key", client=mock_groq)
    gen = client.stream_generate("Prompt")
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as stop:
        final = stop.value

    assert chunks == []
    assert final.first_token_ms is None, "Stream with no content must have null first_token_ms"

# 2. Monotonic clocks and component duration tracking
def test_monotonic_pipeline_timings_and_component_breakdown():
    pipeline = RelayPipeline()
    res = pipeline.run_request(
        query="What is the formula for multi-head attention?",
        request_id="test_mono_01",
        source="stand-in",
        retrieval_setting="setting_b"
    )

    assert res.status == "ok"
    assert res.total_wall_ms is not None
    assert res.total_wall_ms > 0
    assert res.retrieval_ms is not None and res.retrieval_ms >= 0
    assert res.generation_ms is not None and res.generation_ms >= 0
    assert res.verification_ms is not None and res.verification_ms >= 0
    assert res.processing_ms is not None

    # Check timestamp ordering
    ts = res.timestamps
    assert "request_start_perf" in ts
    assert "completion_perf" in ts
    assert ts["request_start_perf"] <= ts["attempt_0_retrieval_start"]
    assert ts["attempt_0_retrieval_start"] <= ts["attempt_0_retrieval_end"]
    assert ts["attempt_0_retrieval_end"] <= ts["attempt_0_generation_start"]
    assert ts["attempt_0_generation_start"] <= ts["attempt_0_generation_end"]
    assert ts["attempt_0_generation_end"] <= ts["attempt_0_verification_start"]
    assert ts["attempt_0_verification_start"] <= ts["attempt_0_verification_end"]
    assert ts["attempt_0_verification_end"] <= ts["completion_perf"]

# 3. Queue depth vs in-flight concurrency tracking
def test_queue_depth_distinct_from_in_flight():
    client = StandInModelClient(rpm_limit=100, fast_mode=True)
    stats0 = client.get_concurrency_stats()
    assert stats0["queue_depth"] == 0
    assert stats0["in_flight"] == 0

    # Queue entrance
    q1 = client.queue_enter()
    q2 = client.queue_enter()
    assert q1 == 1
    assert q2 == 2
    stats_queued = client.get_concurrency_stats()
    assert stats_queued["queue_depth"] == 2
    assert stats_queued["peak_queue_depth"] == 2
    assert stats_queued["in_flight"] == 0  # Still 0 in flight!

    # Queue exit into execution
    client.queue_exit()
    stats_exit = client.get_concurrency_stats()
    assert stats_exit["queue_depth"] == 1
    assert stats_exit["peak_queue_depth"] == 2

    # ConcurrencyTracker helper
    tracker = ConcurrencyTracker()
    adm1, t_sub1 = tracker.submit_task()
    adm2, t_sub2 = tracker.submit_task()
    assert tracker._queue_depth == 2

    wait1, q_adm1, inflight1 = tracker.start_task(t_sub1)
    assert q_adm1 == 2  # Admission queue depth prior to dequeue
    assert inflight1 == 1
    assert wait1 >= 0.0

    wait2, q_adm2, inflight2 = tracker.start_task(t_sub2)
    assert q_adm2 == 1  # Admission queue depth for second task
    assert inflight2 == 2
    assert tracker._queue_depth == 0  # Queue is now empty after both dequeued

    tracker.finish_task()
    tracker.finish_task()
    assert tracker._in_flight == 0
    assert tracker.stats()["peak_queue_depth"] == 2
    assert tracker.stats()["max_concurrency"] == 2

# 4. Actual and estimated tokens are never mixed
def test_actual_and_estimated_tokens_separation_groq():
    mock_groq = MagicMock()
    mock_raw = MagicMock()
    mock_raw.headers = {}
    mock_comp = MagicMock()
    mock_comp.choices = [MagicMock(message=MagicMock(content="Sample response text."))]
    mock_comp.usage.prompt_tokens = 42
    mock_comp.usage.completion_tokens = 15
    mock_comp.usage.total_tokens = 57
    mock_comp.id = "test_usage_id"
    mock_raw.parse.return_value = mock_comp
    mock_groq.chat.completions.with_raw_response.create.return_value = mock_raw

    client = GroqClient(api_key="gsk_dummy", client=mock_groq)
    resp = client.generate("Input prompt for testing token separation.")

    # Actual tokens from provider usage metadata
    assert resp.actual_input_tokens == 42
    assert resp.actual_output_tokens == 15
    assert resp.actual_total_tokens == 57

    # Estimated tokens from heuristic
    assert resp.estimated_input_tokens is not None
    assert resp.estimated_output_tokens is not None
    assert resp.estimated_total_tokens == resp.estimated_input_tokens + resp.estimated_output_tokens
    assert resp.is_simulated is False

def test_actual_tokens_null_when_missing_and_stand_in_simulated():
    # Groq without usage metadata
    mock_groq = MagicMock()
    mock_raw = MagicMock()
    mock_raw.headers = {}
    mock_comp = MagicMock()
    mock_comp.choices = [MagicMock(message=MagicMock(content="No usage text."))]
    mock_comp.usage = None  # Missing usage
    mock_comp.id = "no_usage_id"
    mock_raw.parse.return_value = mock_comp
    mock_groq.chat.completions.with_raw_response.create.return_value = mock_raw

    client = GroqClient(api_key="gsk_dummy", client=mock_groq)
    resp = client.generate("Testing missing usage.")
    assert resp.actual_input_tokens is None
    assert resp.actual_output_tokens is None
    assert resp.actual_total_tokens is None
    assert resp.estimated_input_tokens is not None
    assert resp.estimated_output_tokens is not None

    # StandIn is explicitly simulated
    standin = StandInModelClient(fast_mode=True)
    resp_standin = standin.generate("Testing standin tokens.")
    assert resp_standin.actual_input_tokens is None
    assert resp_standin.actual_output_tokens is None
    assert resp_standin.actual_total_tokens is None
    assert resp_standin.estimated_input_tokens is not None
    assert resp_standin.estimated_output_tokens is not None
    assert resp_standin.is_simulated is True

# 5. Cost is never hardcoded to $0.00
def test_cost_never_hardcoded_to_zero():
    synthetic_rows = [
        {"request_id": "steady_01", "scenario": "steady", "source": "stand-in",
         "start_time": 1000.0, "first_token_ms": 100.0, "total_ms": 200.0, "status": "ok",
         "retries": 0, "tokens_in": 100, "tokens_out": 20, "retrieval_setting": "setting_b", "answer_grade": "correct"},
    ]
    df = pd.DataFrame(synthetic_rows)
    t2a, t2b = generate_table_2a_and_2b(df)

    assert "$0.00" not in t2b, "Cost must never be hardcoded to $0.00"
    assert "N/A" in t2b, "Cost column should report N/A for unbilled/free tier"

# 6. Percentiles handle failed, empty, and small samples
def test_percentile_calculations_handle_failed_and_empty():
    assert compute_percentiles(pd.Series([], dtype=float)) == (None, None, None)
    assert compute_percentiles(pd.Series([0.0, -5.0])) == (None, None, None)
    assert compute_percentiles(pd.Series([None, None])) == (None, None, None)

    # Valid positive series
    p50, p95, p99 = compute_percentiles(pd.Series([100.0, 200.0, 300.0, 400.0, 500.0]))
    assert p50 == 300.0
    assert p95 == 480.0
    assert p99 == 496.0

def test_failed_requests_excluded_from_latency_percentiles():
    synthetic_rows = [
        {"request_id": "burst_01", "scenario": "burst", "source": "stand-in",
         "start_time": 1000.0, "first_token_ms": 150.0, "total_ms": 500.0, "status": "ok",
         "retries": 0, "tokens_in": 100, "tokens_out": 20, "retrieval_setting": "setting_b", "answer_grade": "correct"},
        {"request_id": "burst_02", "scenario": "burst", "source": "stand-in",
         "start_time": 1001.0, "first_token_ms": "", "total_ms": 5.0, "status": "rate_limited",
         "retries": 1, "tokens_in": 100, "tokens_out": 0, "retrieval_setting": "setting_b", "answer_grade": "rate_limited"},
    ]
    df = pd.DataFrame(synthetic_rows)
    t2a, t2b = generate_table_2a_and_2b(df)

    # In Table 2a, TTFT should reflect the 150ms of the successful request, not 0 or 5ms from the 429
    lines = [l for l in t2a.split("\n") if "burst" in l]
    assert len(lines) == 1
    assert "150.0" in lines[0]
    assert "500.0" in lines[0]

# 7. CSV Schema validation handles extended telemetry columns seamlessly
def test_csv_schema_validates_extended_telemetry_columns():
    row = {
        "request_id": "test_ext_01",
        "scenario": "steady",
        "source": "stand-in",
        "start_time": 1000.0,
        "first_token_ms": 120.0,
        "total_ms": 250.0,
        "status": "ok",
        "retries": 0,
        "tokens_in": 80,
        "tokens_out": 25,
        "retrieval_setting": "setting_b",
        "answer_grade": "correct",
        "run_id": "run_ext_test",
        "requested_retrieval_setting": "setting_b",
        "degradation_reason": "",
        "actual_input_tokens": 80,
        "actual_output_tokens": 25,
        "actual_total_tokens": 105,
        "estimated_input_tokens": 75,
        "estimated_output_tokens": 24,
        "estimated_total_tokens": 99,
        "is_simulated": True,
        "retrieval_ms": 45.2,
        "generation_ms": 180.5,
        "verification_ms": 24.3,
        "queue_wait_ms": 0.0,
        "processing_ms": 250.0,
        "total_wall_ms": 250.0,
        "queue_depth": 0,
        "concurrency": 1
    }
    df = pd.DataFrame([row])
    report = validate_results_dataframe(df)
    assert report.is_valid, f"Validation failed: {report.errors}"
    assert report.total_rows == 1
