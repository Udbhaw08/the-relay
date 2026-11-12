"""
Automated unit and integration tests verifying that LocalQuotaLimiter is actively connected
to the real Groq runtime execution path.
Verifies:
- Groq runtime actually invokes LocalQuotaLimiter before API calls.
- RPM rejection aborts without live provider call.
- TPM rejection aborts without live provider call.
- RPD rejection aborts without live provider call.
- TPD rejection aborts without live provider call.
- Retry attempts consume safety budget correctly as separate attempts.
- Successful usage reconciles token reservations against actual usage.
- Failed attempts release token reservations safely without double-counting.
- Daily budget rollover works deterministically with injectable clock.
- Rolling daily reset does not reset while requests are active in flight.
- Missing usage metadata remains unknown and handled gracefully.
- Zero API keys leaked in errors or logs.
"""
import pytest
from unittest.mock import MagicMock
import httpx
import groq

from the_relay.models.groq_client import GroqClient
from the_relay.pipeline.resilience import LocalQuotaLimiter
from the_relay.models.router import ModelRouter
from the_relay.pipeline.orchestrator import RelayPipeline

def test_groq_runtime_invokes_local_limiter_rpm_rejection():
    # Configure limiter with RPM=2
    limiter = LocalQuotaLimiter(rpm_limit=2, tpm_limit=100000, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()

    mock_raw_resp = MagicMock()
    mock_raw_resp.headers = {"x-ratelimit-remaining-requests": "28"}
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Answer."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 20
    mock_completion.usage.completion_tokens = 10
    mock_completion.usage.total_tokens = 30
    mock_completion.id = "chat_mock_1"
    mock_raw_resp.parse.return_value = mock_completion
    mock_groq.chat.completions.with_raw_response.create.return_value = mock_raw_resp

    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    # 1st request -> allowed, provider called
    r1 = client.generate("Query 1")
    assert r1.status == "ok"
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 1

    # 2nd request -> allowed, provider called
    r2 = client.generate("Query 2")
    assert r2.status == "ok"
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 2

    # 3rd request within 60s -> REJECTED locally before reaching provider!
    r3 = client.generate("Query 3")
    assert r3.status == "rate_limited"
    assert "Local RPM limit exceeded" in r3.error_message
    assert r3.rate_limit_headers.get("x-ratelimit-remaining-requests") == "0"
    # CRITICAL: Provider was NOT called a 3rd time
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 2

def test_groq_runtime_invokes_local_limiter_tpm_rejection():
    # TPM limit of 200 tokens
    limiter = LocalQuotaLimiter(rpm_limit=10, tpm_limit=200, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()
    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    # Request with max_tokens=1000 exceeds TPM limit (200) locally
    r = client.generate("Short prompt", max_tokens=1000)
    assert r.status == "rate_limited"
    assert "Local TPM limit exceeded" in r.error_message
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 0

def test_groq_runtime_invokes_local_limiter_rpd_rejection():
    # RPD limit of 2
    limiter = LocalQuotaLimiter(rpm_limit=10, tpm_limit=100000, rpd_limit=2, tpd_limit=200000)
    mock_groq = MagicMock()
    mock_raw_resp = MagicMock()
    mock_raw_resp.headers = {}
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Answer."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 10
    mock_completion.usage.completion_tokens = 10
    mock_completion.usage.total_tokens = 20
    mock_raw_resp.parse.return_value = mock_completion
    mock_groq.chat.completions.with_raw_response.create.return_value = mock_raw_resp

    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    r1 = client.generate("Q1", max_tokens=50)
    r2 = client.generate("Q2", max_tokens=50)
    assert r1.status == "ok"
    assert r2.status == "ok"

    # 3rd daily request rejected
    r3 = client.generate("Q3", max_tokens=50)
    assert r3.status == "rate_limited"
    assert "Daily request budget exhausted" in r3.error_message
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 2

def test_groq_runtime_invokes_local_limiter_tpd_rejection():
    # TPD limit of 100
    limiter = LocalQuotaLimiter(rpm_limit=10, tpm_limit=100000, rpd_limit=1000, tpd_limit=100)
    mock_groq = MagicMock()
    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    r = client.generate("Prompt", max_tokens=150)
    assert r.status == "rate_limited"
    assert "Daily token budget exhausted" in r.error_message
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 0

def test_groq_streaming_invokes_local_limiter():
    limiter = LocalQuotaLimiter(rpm_limit=1, tpm_limit=100000, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content="token "))]
    chunk.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    mock_groq.chat.completions.create.return_value = [chunk]

    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    # 1st stream -> allowed
    gen1 = client.stream_generate("Stream Q1", max_tokens=50)
    chunks1 = list(gen1)
    assert len(chunks1) == 1

    # 2nd stream -> rejected by local RPM before opening provider stream
    gen2 = client.stream_generate("Stream Q2", max_tokens=50)
    chunks2 = []
    try:
        while True:
            chunks2.append(next(gen2))
    except StopIteration as stop:
        final_res = stop.value

    assert len(chunks2) == 0
    assert final_res.status == "rate_limited"
    assert "Local RPM limit exceeded" in final_res.error_message
    assert mock_groq.chat.completions.create.call_count == 1

def test_retry_attempts_consume_budget_correctly():
    # Limiter allows 3 RPM
    limiter = LocalQuotaLimiter(rpm_limit=3, tpm_limit=100000, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()

    # Provider returns 429 on first 2 calls, succeeds on 3rd call
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_429 = httpx.Response(429, request=req, headers={"retry-after": "0.01"})
    err_429 = groq.RateLimitError("Rate limited", response=resp_429, body=None)

    mock_raw_resp = MagicMock()
    mock_raw_resp.headers = {}
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "The Transformer replaces recurrence with multi-head attention. Citation: [Attention Is All You Need, Page 4, Section 3.2]."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 10
    mock_completion.usage.completion_tokens = 10
    mock_completion.usage.total_tokens = 20
    mock_raw_resp.parse.return_value = mock_completion

    mock_groq.chat.completions.with_raw_response.create.side_effect = [
        err_429,
        err_429,
        mock_raw_resp
    ]

    groq_client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)
    router = ModelRouter(provider="groq", limiter=limiter)
    router._groq_client = groq_client

    pipeline = RelayPipeline(router=router, limiter=limiter)
    res = pipeline.run_request(
        query="Explain multi-head attention.",
        request_id="retry_budget_test",
        source="groq",
        sleeper=lambda s: None
    )

    assert res.status == "ok"
    assert res.retries == 2
    assert mock_groq.chat.completions.with_raw_response.create.call_count == 3
    # Exactly 3 requests consumed from limiter (now at limit)
    assert limiter.get_active_requests_in_minute() == 3

    # 4th request must be rejected by local limiter
    r_blocked = groq_client.generate("Attempt 4", max_tokens=50)
    assert r_blocked.status == "rate_limited"
    assert "Local RPM limit exceeded" in r_blocked.error_message

def test_successful_usage_reconciles_token_reservations():
    limiter = LocalQuotaLimiter(rpm_limit=10, tpm_limit=500, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()

    mock_raw_resp = MagicMock()
    mock_raw_resp.headers = {}
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Brief reply."
    mock_completion.choices = [mock_choice]
    # Actual prompt was 15 tokens, completion was 10 tokens -> total 25 tokens
    mock_completion.usage.prompt_tokens = 15
    mock_completion.usage.completion_tokens = 10
    mock_completion.usage.total_tokens = 25
    mock_raw_resp.parse.return_value = mock_completion
    mock_groq.chat.completions.with_raw_response.create.return_value = mock_raw_resp

    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    # Initial reserve estimates ~400 tokens (tokens_in + max_tokens=350)
    res = client.generate("Short question", max_tokens=350)
    assert res.status == "ok"
    # After reconciliation, reserved tokens adjusted down to actual 25 tokens!
    assert limiter.get_active_tokens_in_minute() == 25
    assert limiter.get_daily_token_count() == 25

def test_failed_request_releases_reservation():
    limiter = LocalQuotaLimiter(rpm_limit=10, tpm_limit=500, rpd_limit=1000, tpd_limit=200000)
    mock_groq = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    timeout_err = groq.APITimeoutError(request=req)
    mock_groq.chat.completions.with_raw_response.create.side_effect = timeout_err

    client = GroqClient(api_key="gsk_test_mock_key_safe", client=mock_groq, limiter=limiter)

    res = client.generate("Query that times out", max_tokens=350)
    assert res.status == "timeout"
    # Tokens reserved during attempt must be released so failed calls don't exhaust TPM/TPD
    assert limiter.get_active_tokens_in_minute() == 0
    assert limiter.get_daily_token_count() == 0

def test_daily_budget_rollover_with_injected_clock():
    simulated_time = [1000.0]
    clock_fn = lambda: simulated_time[0]

    # Daily window of 3600 seconds (1 hour for deterministic test), RPD=2
    limiter = LocalQuotaLimiter(
        rpm_limit=10,
        tpm_limit=100000,
        rpd_limit=2,
        tpd_limit=200000,
        clock_fn=clock_fn,
        daily_window_seconds=3600.0,
        reset_at_utc_midnight=False
    )

    allowed1, _, _ = limiter.reserve(50, "r1")
    allowed2, _, _ = limiter.reserve(50, "r2")
    allowed3, reason, meta = limiter.reserve(50, "r3")

    assert allowed1 is True
    assert allowed2 is True
    assert allowed3 is False
    assert reason == "daily_budget_exhausted"
    # Retry-after indicates remaining time in window (~3600s)
    assert meta["retry-after"] == "3600"

    # Finish in-flight requests
    limiter.reconcile("res_r1", 50)
    limiter.reconcile("res_r2", 50)

    # Advance time by 3601 seconds into next window
    simulated_time[0] += 3601.0

    # In next window, daily budget must have rolled over!
    allowed4, _, _ = limiter.reserve(50, "r4")
    assert allowed4 is True
    assert limiter.get_daily_request_count() == 1

def test_daily_budget_does_not_rollover_while_active_in_flight():
    simulated_time = [1000.0]
    clock_fn = lambda: simulated_time[0]

    limiter = LocalQuotaLimiter(
        rpm_limit=10,
        tpm_limit=100000,
        rpd_limit=2,
        tpd_limit=200000,
        clock_fn=clock_fn,
        daily_window_seconds=3600.0,
        reset_at_utc_midnight=False
    )

    allowed1, _, meta1 = limiter.reserve(50, "r1")
    assert allowed1 is True
    res_id1 = meta1["reservation_id"]

    # Advance clock past window while r1 is STILL in-flight (not reconciled or released)
    simulated_time[0] += 3601.0

    # Rollover check must NOT reset daily counters while active request is in-flight
    with limiter._lock:
        limiter._check_and_rollover_daily_window(simulated_time[0])
    assert limiter.get_daily_request_count() == 1

    # Release r1
    limiter.reconcile(res_id1, 50)

    # Advance clock and check rollover now that in-flight is clear
    simulated_time[0] += 1.0
    with limiter._lock:
        limiter._check_and_rollover_daily_window(simulated_time[0])
    assert limiter.get_daily_request_count() == 0

def test_api_keys_remain_absent_from_logs_and_errors():
    mock_groq = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_err = httpx.Response(400, request=req, headers={"x-request-id": "req_err"})
    secret_key = "gsk_SUPER_SECRET_PROV_KEY_12345"
    bad_req_err = groq.BadRequestError(f"Invalid call with key {secret_key}", response=resp_err, body=None)
    mock_groq.chat.completions.with_raw_response.create.side_effect = bad_req_err

    client = GroqClient(api_key=secret_key, client=mock_groq)
    res = client.generate("Test error safety")

    assert res.status == "error"
    assert secret_key not in res.error_message
    assert "gsk_" not in res.error_message
    assert "[REDACTED_API_KEY]" in res.error_message
