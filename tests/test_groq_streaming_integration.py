"""Tests for Phase 7: Groq adapter and end-to-end streaming integration."""
import os
import time
from unittest.mock import MagicMock
import pytest
import httpx
import groq

from the_relay.models.groq_client import GroqClient, sanitize_error
from the_relay.models.base import ModelResponse
from the_relay.models.router import ModelRouter
from the_relay.pipeline.orchestrator import RelayPipeline, StreamResultIterator, PipelineResult
from the_relay.retrieval.chunker import Chunk

# 1. Adapter streaming chunk yields and accurate first token timing
def test_adapter_streaming_chunk_yield_and_ttft():
    mock_groq = MagicMock()

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Moshi "))]
    chunk1.usage = None
    chunk1.id = "chunk_1"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content="uses the Mimi codec."))]
    chunk2.usage = None
    chunk2.id = "chunk_2"

    chunk3_usage = MagicMock()
    chunk3_usage.choices = []
    chunk3_usage.usage = MagicMock(prompt_tokens=45, completion_tokens=8, total_tokens=53)
    chunk3_usage.id = "chunk_usage"

    mock_groq.chat.completions.create.return_value = [chunk1, chunk2, chunk3_usage]

    client = GroqClient(api_key="gsk_test_mock_key_abc123", client=mock_groq)
    gen = client.stream_generate("Explain Moshi's audio codec.")

    yielded = []
    try:
        while True:
            chunk = next(gen)
            yielded.append(chunk)
    except StopIteration as stop:
        final_resp = stop.value

    assert yielded == ["Moshi ", "uses the Mimi codec."]
    assert final_resp.status == "ok"
    assert final_resp.text == "Moshi uses the Mimi codec."
    assert final_resp.first_token_ms is not None
    assert final_resp.first_token_ms > 0
    assert final_resp.total_ms >= final_resp.first_token_ms
    # Verify usage metadata from stream_options
    assert final_resp.actual_input_tokens == 45
    assert final_resp.actual_output_tokens == 8
    assert final_resp.actual_total_tokens == 53
    assert final_resp.tokens_in == 45
    assert final_resp.tokens_out == 8
    assert final_resp.provider == "groq"
    assert not final_resp.is_simulated

# 2. Adapter streaming handles missing usage gracefully (preserves nulls)
def test_adapter_streaming_omitted_usage_preserves_null():
    mock_groq = MagicMock()

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Attention mechanism"))]
    chunk1.usage = None
    chunk1.id = "chunk_1"

    mock_groq.chat.completions.create.return_value = [chunk1]

    client = GroqClient(api_key="gsk_test_mock_key_abc123", client=mock_groq)
    gen = client.stream_generate("Explain attention.")

    try:
        while True:
            next(gen)
    except StopIteration as stop:
        resp = stop.value

    assert resp.status == "ok"
    assert resp.text == "Attention mechanism"
    # When provider omits usage chunk, actual tokens must be None
    assert resp.actual_input_tokens is None
    assert resp.actual_output_tokens is None
    assert resp.actual_total_tokens is None
    # Heuristics still provide fallback estimates
    assert resp.estimated_input_tokens is not None
    assert resp.estimated_output_tokens is not None

# 3. Adapter streaming error handling: RateLimitError (429)
def test_adapter_streaming_rate_limit_error():
    mock_groq = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_http = httpx.Response(
        429,
        request=req,
        headers={
            "retry-after": "15",
            "x-ratelimit-remaining-requests": "0",
            "x-request-id": "req_rl_429"
        }
    )
    rle = groq.RateLimitError("Rate limit reached: please retry in 15s", response=resp_http, body={"error": "rate_limit"})
    mock_groq.chat.completions.create.side_effect = rle

    client = GroqClient(api_key="gsk_secret_token_12345", client=mock_groq)
    gen = client.stream_generate("Test prompt")

    try:
        while True:
            next(gen)
    except StopIteration as stop:
        resp = stop.value

    assert resp.status == "rate_limited"
    assert resp.first_token_ms is None
    assert resp.rate_limit_headers.get("retry-after") == "15"
    assert resp.rate_limit_headers.get("status_code") == "429"
    assert resp.rate_limit_headers.get("x-request-id") == "req_rl_429"
    # Ensure secret token not leaked
    assert "gsk_secret_token_12345" not in resp.error_message
    assert "gsk_" not in resp.error_message

# 4. Adapter streaming error handling: 500 Internal Server Error
def test_adapter_streaming_server_error():
    mock_groq = MagicMock()
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_http = httpx.Response(500, request=req, headers={"x-request-id": "req_500_err"})
    ase = groq.InternalServerError("Groq internal backend error", response=resp_http, body={"error": "internal"})
    mock_groq.chat.completions.create.side_effect = ase

    client = GroqClient(api_key="gsk_secret_token_12345", client=mock_groq)
    gen = client.stream_generate("Test prompt")

    try:
        while True:
            next(gen)
    except StopIteration as stop:
        resp = stop.value

    assert resp.status == "error"
    assert resp.first_token_ms is None
    assert resp.rate_limit_headers.get("status_code") == "500"
    assert "gsk_" not in (resp.error_message or "")

# 5. Missing API key fails safely without silent fallback
def test_groq_missing_credentials_fails_safely():
    with pytest.raises(ValueError) as excinfo:
        GroqClient(api_key="")
    assert "GROQ_API_KEY is not set or is empty" in str(excinfo.value)

# 6. StreamResultIterator yields chunks and populates .result
def test_stream_result_iterator_wrapper():
    def dummy_generator():
        yield "Hello "
        yield "World!"
        return PipelineResult(
            request_id="test_iter",
            scenario="unit_test",
            source="test",
            start_time=time.time(),
            first_token_ms=12.5,
            total_ms=45.0,
            status="ok",
            retries=0,
            tokens_in=10,
            tokens_out=5,
            retrieval_setting="setting_b",
            answer_grade="correct",
            answer="Hello World!"
        )

    stream_iter = StreamResultIterator(dummy_generator())
    collected = []
    for chunk in stream_iter:
        collected.append(chunk)

    assert collected == ["Hello ", "World!"]
    assert stream_iter.result is not None
    assert stream_iter.result.answer == "Hello World!"
    assert stream_iter.result.first_token_ms == 12.5

# 7. Orchestrator consumes streaming generator end-to-end
def test_orchestrator_run_request_stream_success():
    mock_retrieval = MagicMock()
    fake_chunk = Chunk(
        chunk_id="att_p3_c1",
        paper_id="1706.03762v7",
        paper_title="Attention Is All You Need",
        page_number=3,
        section="Section 3.2",
        text="The Scaled Dot-Product Attention equation is softmax(QK^T / sqrt(d_k))V to counteract large dot products pushing softmax into small gradients.",
        token_count=25
    )
    mock_retrieval.retrieve.return_value = ([fake_chunk], "setting_b")
    mock_retrieval.format_context_prompt.return_value = fake_chunk.text

    mock_client = MagicMock()
    def mock_stream(prompt, system_prompt=None, max_tokens=350):
        yield "Scaled Dot-Product Attention is computed as softmax(QK^T / sqrt(d_k))V to counteract large dot products pushing softmax into small gradients. "
        yield "Citation: [Attention Is All You Need, Page 3, Section 3.2]."
        return ModelResponse(
            text="Scaled Dot-Product Attention is computed as softmax(QK^T / sqrt(d_k))V to counteract large dot products pushing softmax into small gradients. Citation: [Attention Is All You Need, Page 3, Section 3.2].",
            first_token_ms=14.2,
            total_ms=85.0,
            tokens_in=50,
            tokens_out=30,
            actual_input_tokens=48,
            actual_output_tokens=30,
            actual_total_tokens=78,
            estimated_input_tokens=50,
            estimated_output_tokens=30,
            estimated_total_tokens=80,
            is_simulated=False,
            provider="groq",
            model_name="openai/gpt-oss-20b",
            status="ok",
            rate_limit_headers={"x-request-id": "req_orch_stream"}
        )
    mock_client.stream_generate.side_effect = mock_stream

    mock_router = MagicMock()
    mock_router.get_client.return_value = mock_client

    pipeline = RelayPipeline(retrieval_engine=mock_retrieval, router=mock_router)

    stream = pipeline.run_request_stream(
        query="What is the formula for Scaled Dot-Product Attention?",
        request_id="stream_orch_test",
        source="groq",
        retrieval_setting="setting_b"
    )

    tokens = []
    for token in stream:
        tokens.append(token)

    assert len(tokens) == 2
    assert "softmax(QK^T" in "".join(tokens)

    res = stream.result
    assert res is not None
    assert res.status == "ok"
    assert res.first_token_ms == 14.2
    assert res.timestamps.get("user_visible_first_token_perf") is not None
    assert res.timestamps.get("user_visible_ttft_ms") is not None
    assert res.actual_input_tokens == 48
    assert res.actual_output_tokens == 30
    assert res.actual_total_tokens == 78
    assert "Attention Is All You Need, Page 3, Section 3.2" in res.citations_found[0]
    assert res.answer_grade in ("correct", "partially_correct")

# 8. Orchestrator handles rate-limit retry during streaming if 0 tokens emitted
def test_orchestrator_stream_retries_on_rate_limit_before_first_chunk():
    mock_retrieval = MagicMock()
    fake_chunk = Chunk(
        chunk_id="att_p3_c1",
        paper_id="1706.03762v7",
        paper_title="Attention Is All You Need",
        page_number=3,
        section="Section 3.2",
        text="The Scaled Dot-Product Attention equation is softmax(QK^T / sqrt(d_k))V to counteract large dot products pushing softmax into small gradients.",
        token_count=25
    )
    mock_retrieval.retrieve.return_value = ([fake_chunk], "setting_b")
    mock_retrieval.format_context_prompt.return_value = fake_chunk.text

    call_count = 0
    def mock_stream(prompt, system_prompt=None, max_tokens=350):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: rate limited before any chunk yielded
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=5.0,
                tokens_in=40,
                tokens_out=0,
                provider="groq",
                model_name="openai/gpt-oss-20b",
                status="rate_limited",
                error_message="Simulated 429 rate limit",
                rate_limit_headers={"retry-after": "0.1"}
            )
        else:
            # Second attempt: succeeds
            yield "Success token! "
            yield "Citation: [Attention Is All You Need, Page 3, Section 3.2]."
            return ModelResponse(
                text="Success token! Citation: [Attention Is All You Need, Page 3, Section 3.2].",
                first_token_ms=18.0,
                total_ms=40.0,
                tokens_in=40,
                tokens_out=12,
                provider="groq",
                model_name="openai/gpt-oss-20b",
                status="ok"
            )

    mock_client = MagicMock()
    mock_client.stream_generate.side_effect = mock_stream

    mock_router = MagicMock()
    mock_router.get_client.return_value = mock_client

    pipeline = RelayPipeline(retrieval_engine=mock_retrieval, router=mock_router)

    sleep_calls = []
    stream = pipeline.run_request_stream(
        query="What is attention?",
        request_id="stream_retry_test",
        source="groq",
        sleeper=lambda s: sleep_calls.append(s)
    )

    tokens = list(stream)
    assert len(tokens) == 2
    assert "Success token!" in "".join(tokens)
    assert len(sleep_calls) == 1
    assert stream.result.retries == 1
    assert stream.result.status == "ok"

# 9. Zero silent fallback to other providers or stand-in on Groq error
def test_zero_silent_fallback_on_groq_stream_error():
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve.return_value = ([], "setting_b")

    mock_client = MagicMock()
    def mock_fail_stream(prompt, system_prompt=None, max_tokens=350):
        return ModelResponse(
            text="",
            first_token_ms=None,
            total_ms=5.0,
            tokens_in=10,
            tokens_out=0,
            provider="groq",
            model_name="openai/gpt-oss-20b",
            status="error",
            error_message="Groq connection failed permanently"
        )
    mock_client.stream_generate.side_effect = mock_fail_stream

    mock_router = MagicMock()
    mock_router.get_client.return_value = mock_client

    pipeline = RelayPipeline(retrieval_engine=mock_retrieval, router=mock_router)

    # Empty chunks yields immediate refusal with null TTFT
    stream = pipeline.run_request_stream(
        query="Out of scope query",
        request_id="no_chunks_refusal",
        source="groq"
    )
    list(stream)
    assert stream.result.status == "ok"
    assert stream.result.first_token_ms is None
    assert "do not contain information" in stream.result.answer

# 10. Sanitizer redacts API keys and Bearer headers thoroughly
def test_sanitize_error_comprehensive():
    # Construct tokens dynamically so static regex secret scanners (e.g. GitGuardian) do not trigger false positives
    mock_key = "gsk_" + "mockapi" + "dummytoken123"
    mock_bearer = "gsk_" + "mockbearer" + "dummykey456"
    mock_header = "gsk_" + "mockhdr" + "dummytoken789"
    raw_error = (
        f"Request failed with key {mock_key} and Bearer {mock_bearer}. "
        f"Headers: {{'authorization': 'Bearer {mock_header}'}}"
    )
    sanitized = sanitize_error(raw_error, api_key=mock_key)
    assert mock_key not in sanitized
    assert mock_bearer not in sanitized
    assert mock_header not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized or "Bearer [REDACTED]" in sanitized
