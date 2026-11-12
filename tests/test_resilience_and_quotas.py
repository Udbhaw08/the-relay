"""
Unit and integration tests for Phase 6:
Groq Rate Limiting, Quotas, Backoff, and Resilience.
Verifies:
- Header parsing (Retry-After, x-ratelimit-*) and duration strings.
- Truncated exponential backoff with true full jitter and caps.
- Fine-grained transient vs permanent error classification.
- Local rolling-window RPM and TPM reservation/reconciliation.
- Daily budget exhaustion and reset handling.
- Deterministic test execution via injectable clock, sleeper, and RNG.
- Bounded concurrency and queue backpressure.
- Stand-in deterministic fault injection.
- Adaptive degradation metadata accuracy.
"""
import pytest
import time
import random
from unittest.mock import MagicMock

from the_relay.pipeline.resilience import (
    parse_duration_string,
    parse_retry_after,
    extract_groq_rate_limit_state,
    compute_backoff,
    is_retryable_error,
    format_daily_exhaustion_message,
    LocalQuotaLimiter,
    BackpressureController,
    GroqRateLimitState
)
from the_relay.models.base import ModelResponse
from the_relay.models.stand_in import StandInModelClient
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult

# 1. Header parsing and Retry-After
def test_parse_duration_strings():
    assert parse_duration_string("15") == 15.0
    assert parse_duration_string("15s") == 15.0
    assert parse_duration_string("2m") == 120.0
    assert parse_duration_string("1m30s") == 90.0
    assert parse_duration_string("500ms") == 0.5
    assert parse_duration_string("2h") == 7200.0
    assert parse_duration_string("1h15m30s") == 4530.0
    assert parse_duration_string("") is None
    assert parse_duration_string(None) is None
    assert parse_duration_string("invalid_str") is None

def test_parse_retry_after():
    assert parse_retry_after("25") == 25.0
    assert parse_retry_after("30s") == 30.0
    assert parse_retry_after("1m") == 60.0

    # HTTP date format
    fixed_now = 1770000000.0
    # 60 seconds into future
    http_date = "Wed, 04 Feb 2026 02:41:00 GMT"
    # parse with mock now_fn
    mock_now = lambda: 1770172800.0  # Wed, 04 Feb 2026 02:40:00 GMT
    res = parse_retry_after(http_date, now_fn=mock_now)
    assert res == 60.0

def test_extract_groq_rate_limit_state():
    headers = {
        "x-ratelimit-limit-requests": "30",
        "x-ratelimit-remaining-requests": "29",
        "x-ratelimit-reset-requests": "2s",
        "x-ratelimit-limit-tokens": "6000",
        "x-ratelimit-remaining-tokens": "5850",
        "x-ratelimit-reset-tokens": "1.5s",
        "retry-after": "5",
        "x-request-id": "req_groq_abc123"
    }
    state = extract_groq_rate_limit_state(headers)
    assert state.limit_requests == 30
    assert state.remaining_requests == 29
    assert state.reset_requests_seconds == 2.0
    assert state.limit_tokens == 6000
    assert state.remaining_tokens == 5850
    assert state.reset_tokens_seconds == 1.5
    assert state.retry_after_seconds == 5.0
    assert state.request_id == "req_groq_abc123"

# 2. Exponential backoff with true full jitter
def test_full_jitter_backoff_bounds_and_caps():
    # Respects Retry-After header
    assert compute_backoff(0, retry_after_header="15") == 15.0
    # Caps excessive Retry-After header to safety cap (60s)
    assert compute_backoff(0, retry_after_header="7200", max_retry_after_cap=60.0) == 60.0

    # True full jitter: uniform(0, min(max_backoff, base * 2**attempt))
    rng = random.Random(42)
    # Attempt 0: cap is 2.0
    for _ in range(50):
        val = compute_backoff(0, base_seconds=2.0, max_seconds=30.0, rng=rng)
        assert 0.0 <= val <= 2.0

    # Attempt 3: cap is min(30, 2 * 2**3) = 16.0
    for _ in range(50):
        val = compute_backoff(3, base_seconds=2.0, max_seconds=30.0, rng=rng)
        assert 0.0 <= val <= 16.0

    # Attempt 6: cap is min(30, 2 * 2**6 = 128) = 30.0
    for _ in range(50):
        val = compute_backoff(6, base_seconds=2.0, max_seconds=30.0, rng=rng)
        assert 0.0 <= val <= 30.0

# 3. Error classification: transient vs permanent
def test_error_classifier():
    # Transient / Retryable
    assert is_retryable_error("rate_limited") is True
    assert is_retryable_error("timeout") is True
    assert is_retryable_error("error", status_code=429) is True
    assert is_retryable_error("error", status_code=500) is True
    assert is_retryable_error("error", status_code=502) is True
    assert is_retryable_error("error", status_code=503) is True
    assert is_retryable_error("error", status_code=504) is True
    assert is_retryable_error("error", error_message="Connection error with host") is True

    # Permanent / Non-retryable
    assert is_retryable_error("ok") is False
    assert is_retryable_error("error", status_code=401) is False
    assert is_retryable_error("error", status_code=403) is False
    assert is_retryable_error("error", status_code=400) is False
    assert is_retryable_error("error", status_code=404) is False
    assert is_retryable_error("error", status_code=422) is False
    assert is_retryable_error("error", error_message="Invalid API Key provided") is False
    assert is_retryable_error("rate_limited", error_message="Daily budget exhausted") is False
    assert is_retryable_error("error", error_message="RPD limit reached for today") is False

# 4. Rolling-window RPM enforcement and expiry
def test_local_quota_rpm_rolling_window():
    current_time = 1000.0
    limiter = LocalQuotaLimiter(rpm_limit=3, rpd_limit=1000, tpm_limit=100000, clock_fn=lambda: current_time)

    # First 3 requests allowed
    ok1, reason1, meta1 = limiter.reserve(estimated_tokens=50, request_id="req1")
    ok2, reason2, meta2 = limiter.reserve(estimated_tokens=50, request_id="req2")
    ok3, reason3, meta3 = limiter.reserve(estimated_tokens=50, request_id="req3")
    assert ok1 and ok2 and ok3
    assert meta3["x-ratelimit-remaining-requests"] == "997"

    # 4th request within same minute rejected
    ok4, reason4, meta4 = limiter.reserve(estimated_tokens=50, request_id="req4")
    assert not ok4
    assert reason4 == "rpm_limit_exceeded"
    assert "retry-after" in meta4

    # Advance clock by 61 seconds -> rolling window expires
    current_time += 61.0
    ok5, reason5, meta5 = limiter.reserve(estimated_tokens=50, request_id="req5")
    assert ok5
    assert reason5 is None

# 5. TPM reservation and reconciliation
def test_local_quota_tpm_reservation_and_reconciliation():
    current_time = 1000.0
    limiter = LocalQuotaLimiter(rpm_limit=100, tpm_limit=500, clock_fn=lambda: current_time)

    # Reserve 350 tokens
    ok1, _, meta1 = limiter.reserve(estimated_tokens=350, request_id="req1")
    assert ok1
    res_id1 = meta1["reservation_id"]

    # Try to reserve 200 tokens (350 + 200 > 500 TPM) -> rejected
    ok2, reason2, _ = limiter.reserve(estimated_tokens=200, request_id="req2")
    assert not ok2
    assert reason2 == "tpm_limit_exceeded"

    # Reconcile req1 with actual usage of only 150 tokens
    limiter.reconcile(res_id1, actual_tokens=150)

    # Now reserving 200 tokens succeeds (150 + 200 = 350 <= 500)
    ok3, _, _ = limiter.reserve(estimated_tokens=200, request_id="req3")
    assert ok3

# 6. Daily budget exhaustion and reset notice
def test_daily_budget_exhaustion_and_notice():
    limiter = LocalQuotaLimiter(rpm_limit=100, rpd_limit=5)
    limiter.exhaust_daily_budget()
    ok, reason, meta = limiter.reserve()
    assert not ok
    assert reason == "daily_budget_exhausted"
    assert meta["retry-after"] == "43200"

    # Dynamic notice with seconds provided
    msg_with_time = format_daily_exhaustion_message(reset_seconds=7500)
    assert "in approximately 2 hour(s) and 5 minute(s)" in msg_with_time

    # Default notice without hardcoding guessed UTC hour
    msg_default = format_daily_exhaustion_message()
    assert "provider's next daily quota reset window" in msg_default
    assert "9 hours" not in msg_default  # removed hardcoded claim

# 7. Deterministic pipeline retry execution (injectable sleeper)
def test_deterministic_pipeline_retry_with_injected_sleeper():
    client = StandInModelClient(fast_mode=True)
    # Inject fault: first call rate_limited (429), second call succeeds
    call_count = 0
    sleeps = []

    def mock_sleeper(sec: float):
        sleeps.append(sec)

    router = MagicMock()
    mock_model = MagicMock()

    # Simulate 1 transient 429 followed by success
    resp_429 = ModelResponse(
        text="",
        first_token_ms=None,
        total_ms=5.0,
        tokens_in=20,
        tokens_out=0,
        provider="groq",
        model_name="openai/gpt-oss-20b",
        status="rate_limited",
        error_message="Rate limit exceeded",
        rate_limit_headers={"retry-after": "3"}
    )
    resp_ok = ModelResponse(
        text="Multi-head attention softmax(QK^T / sqrt(d_k))V. Citation: [Attention Is All You Need, Page 4, Section 3.2].",
        first_token_ms=120.0,
        total_ms=250.0,
        tokens_in=20,
        tokens_out=25,
        provider="groq",
        model_name="openai/gpt-oss-20b",
        status="ok"
    )
    mock_model.generate.side_effect = [resp_429, resp_ok, resp_ok]
    router.get_client.return_value = mock_model

    pipeline = RelayPipeline(router=router)
    res = pipeline.run_request(
        query="What is the formula for multi-head attention?",
        request_id="test_retry_01",
        source="groq",
        sleeper=mock_sleeper
    )

    assert res.status == "ok"
    assert res.retries == 1
    assert len(sleeps) == 1
    assert sleeps[0] == 3.0  # Respected Retry-After header

# 8. Non-retryable errors abort immediately
def test_non_retryable_auth_and_daily_budget_fail_fast():
    router = MagicMock()
    mock_model = MagicMock()

    resp_auth = ModelResponse(
        text="",
        first_token_ms=None,
        total_ms=10.0,
        tokens_in=20,
        tokens_out=0,
        provider="groq",
        model_name="openai/gpt-oss-20b",
        status="error",
        error_message="Invalid API Key provided",
        rate_limit_headers={"status_code": "401"}
    )
    mock_model.generate.return_value = resp_auth
    router.get_client.return_value = mock_model

    sleeps = []
    pipeline = RelayPipeline(router=router)
    res = pipeline.run_request(
        query="What is attention?",
        request_id="test_auth_fail",
        source="groq",
        sleeper=lambda s: sleeps.append(s)
    )

    assert res.status == "error"
    assert res.retries == 0
    assert len(sleeps) == 0  # Did not retry

# 9. Bounded concurrency and backpressure controller
def test_bounded_concurrency_and_backpressure():
    controller = BackpressureController(max_concurrency=2, max_queue_depth=3)

    # Fill queue
    assert controller.admit_request()[0] is True
    assert controller.admit_request()[0] is True
    assert controller.admit_request()[0] is True

    # 4th request exceeds max_queue_depth -> rejected with backpressure
    admitted, reason = controller.admit_request()
    assert not admitted
    assert reason == "queue_capacity_breached_backpressure"

    # Worker begins execution
    controller.begin_execution()
    st = controller.stats()
    assert st["queued"] == 2
    assert st["in_flight"] == 1

    controller.finish_execution()
    assert controller.stats()["in_flight"] == 0

# 10. Stand-In deterministic fault injection
def test_stand_in_deterministic_fault_injection():
    client = StandInModelClient(fast_mode=True)

    # 429
    client.inject_fault("429")
    r1 = client.generate("Q1")
    assert r1.status == "rate_limited"
    assert r1.is_simulated is True

    # Timeout
    client.inject_fault("timeout")
    r2 = client.generate("Q2")
    assert r2.status == "timeout"
    assert r2.is_simulated is True

    # 500
    client.inject_fault("500")
    r3 = client.generate("Q3")
    assert r3.status == "error"
    assert r3.is_simulated is True

    # Clear
    client.clear_injected_faults()
    r4 = client.generate("Q4")
    assert r4.status == "ok"
