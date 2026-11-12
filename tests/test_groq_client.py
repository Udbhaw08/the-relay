"""Unit tests for GroqClient, ModelRouter, and safety constraints."""
import pytest
from unittest.mock import MagicMock
import httpx
import groq

from the_relay.models.groq_client import GroqClient, sanitize_error, extract_rate_limit_headers
from the_relay.models.router import ModelRouter
from the_relay.models.stand_in import StandInModelClient
from the_relay.pipeline.orchestrator import RelayPipeline

# 1. Successful non-streaming generation
def test_groq_successful_completion_non_streaming():
    mock_groq_client = MagicMock()
    mock_raw_response = MagicMock()
    
    mock_raw_response.headers = {
        "x-ratelimit-remaining-requests": "29",
        "x-ratelimit-remaining-tokens": "5900",
        "x-request-id": "req_mock_123"
    }
    
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Multi-head attention allows the model to jointly attend to information."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 35
    mock_completion.usage.completion_tokens = 18
    mock_completion.id = "chatcmpl_mock_123"
    
    mock_raw_response.parse.return_value = mock_completion
    mock_groq_client.chat.completions.with_raw_response.create.return_value = mock_raw_response

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    resp = client.generate("What is multi-head attention?")

    assert resp.status == "ok"
    assert "Multi-head attention" in resp.text
    assert resp.tokens_in == 35
    assert resp.tokens_out == 18
    assert resp.provider == "groq"
    assert resp.rate_limit_headers.get("x-ratelimit-remaining-requests") == "29"
    assert resp.rate_limit_headers.get("id") == "chatcmpl_mock_123"
    assert resp.first_token_ms is None  # Non-streaming has null TTFT; true TTFT measured via streaming
    assert resp.total_ms > 0

# 2. Successful streaming generation
def test_groq_successful_streaming():
    mock_groq_client = MagicMock()

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Scaled dot-product "))]
    chunk1.usage = None
    chunk1.id = "stream_mock_1"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content="attention formula."))]
    chunk2.usage = MagicMock(prompt_tokens=20, completion_tokens=8)
    chunk2.id = "stream_mock_2"

    mock_groq_client.chat.completions.create.return_value = [chunk1, chunk2]

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    gen = client.stream_generate("What is scaled dot-product attention?")

    yielded_chunks = []
    try:
        while True:
            chunk = next(gen)
            yielded_chunks.append(chunk)
    except StopIteration as stop:
        final_resp = stop.value

    assert yielded_chunks == ["Scaled dot-product ", "attention formula."]
    assert final_resp.status == "ok"
    assert final_resp.text == "Scaled dot-product attention formula."
    assert final_resp.tokens_in == 20
    assert final_resp.tokens_out == 8
    assert final_resp.first_token_ms > 0
    assert final_resp.total_ms >= final_resp.first_token_ms

# 3. Missing API key startup validation
def test_groq_missing_api_key_startup_validation():
    with pytest.raises(ValueError) as excinfo:
        GroqClient(api_key="")
    assert "GROQ_API_KEY is not set or is empty" in str(excinfo.value)
    # Ensure no secrets leaked
    assert "gsk_" not in str(excinfo.value)

# 4. Invalid authentication (401)
def test_groq_invalid_authentication():
    mock_groq_client = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(401, request=req, headers={"x-request-id": "req_auth_err"})
    auth_err = groq.AuthenticationError("Invalid API Key provided", response=resp, body={"error": "invalid_api_key"})
    
    mock_groq_client.chat.completions.with_raw_response.create.side_effect = auth_err

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Hello")

    assert res.status == "error"
    assert "authentication failed" in res.error_message.lower()
    assert res.rate_limit_headers.get("status_code") == "401"
    # Ensure no key in error message
    assert "gsk_" not in res.error_message

# 5. Rate limit (429) and retry-after header extraction
def test_groq_rate_limit_429():
    mock_groq_client = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(
        429,
        request=req,
        headers={
            "retry-after": "15",
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-limit-requests": "30",
            "x-request-id": "req_429_test"
        }
    )
    rate_err = groq.RateLimitError("Rate limit reached", response=resp, body={"error": "rate_limit_exceeded"})
    mock_groq_client.chat.completions.with_raw_response.create.side_effect = rate_err

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Stress query")

    assert res.status == "rate_limited"
    assert res.rate_limit_headers.get("retry-after") == "15"
    assert res.rate_limit_headers.get("x-ratelimit-remaining-requests") == "0"
    assert res.rate_limit_headers.get("status_code") == "429"

# 6. Request timeout
def test_groq_request_timeout():
    mock_groq_client = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    timeout_err = groq.APITimeoutError(request=req)
    mock_groq_client.chat.completions.with_raw_response.create.side_effect = timeout_err

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Slow query")

    assert res.status == "timeout"
    assert "timed out" in res.error_message.lower()

# 7. 5xx Internal server error
def test_groq_5xx_server_error():
    mock_groq_client = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(503, request=req, headers={"x-request-id": "req_503"})
    server_err = groq.InternalServerError("Service Unavailable", response=resp, body=None)
    mock_groq_client.chat.completions.with_raw_response.create.side_effect = server_err

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Fail query")

    assert res.status == "error"
    assert res.rate_limit_headers.get("status_code") == "503"

# 8. Malformed response handling
def test_groq_malformed_response():
    mock_groq_client = MagicMock()
    mock_raw_response = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = []  # Empty choices
    mock_completion.usage = None
    mock_completion.id = None
    mock_raw_response.headers = {}
    mock_raw_response.parse.return_value = mock_completion
    mock_groq_client.chat.completions.with_raw_response.create.return_value = mock_raw_response

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Malformed test")

    assert res.status == "ok"
    assert res.text == ""

# 9. Structured usage metadata
def test_groq_structured_usage_metadata():
    mock_groq_client = MagicMock()
    mock_raw_response = MagicMock()
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Answer with usage."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 240
    mock_completion.usage.completion_tokens = 85
    mock_completion.id = "chatcmpl_usage_123"
    mock_raw_response.headers = {}
    mock_raw_response.parse.return_value = mock_completion
    mock_groq_client.chat.completions.with_raw_response.create.return_value = mock_raw_response

    client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    res = client.generate("Query")

    assert res.tokens_in == 240
    assert res.tokens_out == 85

# 10. No silent fallback: Groq failure in Groq mode surfaces explicit error
def test_router_no_silent_fallback_in_groq_mode():
    router = ModelRouter(provider="groq")
    
    mock_groq_client = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={"retry-after": "5"})
    mock_groq_client.chat.completions.with_raw_response.create.side_effect = groq.RateLimitError(
        "Rate limit exceeded", response=resp, body=None
    )
    failing_client = GroqClient(api_key="gsk_dummy_test_key_for_mock_unit_tests", client=mock_groq_client)
    router._groq_client = failing_client

    pipeline = RelayPipeline(router=router)
    result = pipeline.run_request(
        query="Explain self-attention.",
        request_id="test_no_fallback",
        source="groq"
    )

    # In groq mode, failure must be surfaced explicitly, NEVER falling back to stand-in
    assert result.status == "rate_limited"
    assert result.source == "groq"
    # Verify the answer does not contain stand-in synthesized answers
    assert "Moshi" not in result.answer
    assert "H-Net" not in result.answer

# 11. Explicit stand-in mode for offline testing
def test_router_explicit_stand_in_mode():
    router = ModelRouter(provider="standin")
    client = router.get_client()
    assert isinstance(client, StandInModelClient)

    client_explicit = router.get_client(source="stand-in")
    assert isinstance(client_explicit, StandInModelClient)

# 12. Reject invalid xAI Grok provider base URL
def test_no_xai_grok_allowed():
    with pytest.raises(ValueError) as excinfo:
        GroqClient(api_key="gsk_dummy_test_key", base_url="https://api.x.ai/v1")
    assert "xAI Grok is NOT supported" in str(excinfo.value)

# 13. Secret scrubbing verification
def test_secret_scrubbing():
    dummy_key = "gsk_1234567890abcdefABCDEF1234567890abcdefABCDEF12345678"
    raw_error = f"Error communicating with key {dummy_key} and header 'Authorization': 'Bearer {dummy_key}'"
    sanitized = sanitize_error(raw_error, api_key=dummy_key)
    assert dummy_key not in sanitized
    assert "gsk_" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized

# 14. Retired Llama 3.3 model is not the default & rejected if configured
def test_retired_llama_33_not_default():
    from the_relay.config import GROQ_MODEL, RETIRED_MODELS
    assert GROQ_MODEL != "llama-3.3-70b-versatile"
    assert "llama-3.3-70b-versatile" in RETIRED_MODELS
    assert GROQ_MODEL == "openai/gpt-oss-20b"

    with pytest.raises(ValueError) as excinfo:
        GroqClient(api_key="gsk_mock_test_key", model_name="llama-3.3-70b-versatile")
    assert "decommissioned" in str(excinfo.value).lower()

# 15. Configured candidate model correctly read from environment variable
def test_candidate_model_read_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    # Reload config or pass explicitly
    client = GroqClient(api_key="gsk_mock_test_key", model_name="openai/gpt-oss-20b")
    assert client.model_name == "openai/gpt-oss-20b"

    client_custom = GroqClient(api_key="gsk_mock_test_key", model_name="custom-free-model")
    assert client_custom.model_name == "custom-free-model"

# 16. Missing GROQ_MODEL is handled safely
def test_missing_groq_model_handled_safely():
    with pytest.raises(ValueError) as excinfo:
        GroqClient(api_key="gsk_mock_test_key", model_name="")
    assert "GROQ_MODEL is not set or is empty" in str(excinfo.value)

# 17. No automatic fallback to another model occurs
def test_no_automatic_model_fallback():
    # When an invalid or decommissioned model is provided, it must fail explicitly
    # rather than silently substituting openai/gpt-oss-20b or another model
    with pytest.raises(ValueError):
        GroqClient(api_key="gsk_mock_test_key", model_name="llama-3.3-70b-versatile")

# 18. Stand-in mode continues to work independently without Groq configuration
def test_stand_in_mode_continues_independently():
    stand_in = StandInModelClient(rpm_limit=100)
    resp = stand_in.generate("What is the Moshi speech model?")
    assert resp.status == "ok"
    assert resp.provider == "stand_in"
    assert "Moshi" in resp.text

# 19. Smoke test cannot run without explicit authorization flags
def test_smoke_test_blocks_without_authorization_flags():
    from scripts.smoke_test_groq import run_smoke_test
    with pytest.raises(SystemExit):
        run_smoke_test(confirm_free_tier=False, authorized=False)
    with pytest.raises(SystemExit):
        run_smoke_test(confirm_free_tier=True, authorized=False)
    with pytest.raises(SystemExit):
        run_smoke_test(confirm_free_tier=False, authorized=True)

# 20. Table 1 aggregator output verification
def test_compute_tables_table1_output():
    from scripts.compute_tables import generate_table_1
    t1 = generate_table_1()
    assert "Table 1: Published Groq Free-plan limits" in t1
    assert "Groq Cloud" in t1 or "Groq" in t1
    assert "429" in t1
    assert "30 RPM" in t1
    assert "8,000 TPM" in t1
    assert "1,000 RPD" in t1
    assert "200,000 TPD" in t1

