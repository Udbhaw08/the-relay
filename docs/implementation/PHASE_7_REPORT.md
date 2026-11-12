# Phase 7 Report: Groq Adapter and End-to-End Streaming Integration

**Date:** 2026-11-12
**Branch:** `feat/the-relay-groq-hardening`
**Execution Status:** Completed

---

## 1. Executive Summary

Phase 7 connects the GroqCloud API adapter (`the_relay/models/groq_client.py`) into the full end-to-end multi-step agentic pipeline. Previously, streaming was implemented in the adapter layer, but higher-level consumers (the orchestrator, CLI tool, and web dashboard) were limited to synchronous batched generation.

Phase 7 delivers:
1. **End-to-End Streaming Orchestration:** Added `step_3_stream_reply(...)` and `run_request_stream(...)` to `the_relay/pipeline/orchestrator.py`, powered by the `StreamResultIterator` wrapper that streams tokens piece-by-piece in real time while capturing the final `PipelineResult` with complete telemetry, evidence-grounded citations, and factual grading upon completion.
2. **Provider TTFT vs. User-Visible TTFT:** Preserved strict mathematical separation between provider time-to-first-token (`resp.first_token_ms`, measured from invocation of the model client to first non-empty token arrival) and user-visible time-to-first-token (`timestamps["user_visible_ttft_ms"]`, measuring elapsed wall-clock latency including upstream intent parsing and passage retrieval).
3. **Usage Metadata Propagation:** Extracted structured usage tokens (`prompt_tokens`, `completion_tokens`, `total_tokens`) from the streaming chunk footer (`stream_options={"include_usage": True}`) and propagated them through `ModelResponse` to `PipelineResult`. Preserved `None` when usage is omitted upstream.
4. **Resilient Exception Handling & Sanitization:** Handled `429 RateLimitError`, `401 AuthenticationError`, `APITimeoutError`, `500 InternalServerError`, and `APIStatusError` in streaming mode without exposing secrets or Bearer tokens. Allowed retry on rate limits before any token is emitted.
5. **CLI & Web Dashboard Streaming:** Added `--stream` flag to `scripts/ask.py` for terminal streaming and added a real-time streaming toggle (`st.write_stream`) to `dashboard/app.py` with safe `N/A` formatting for null TTFT values.
6. **Isolated Opt-In Live Testing:** Added `tests/test_groq_live_opt_in.py`, skipped by default during normal test runs and CI to strictly protect unverified API quotas. Added 10 mocked unit and integration tests in `tests/test_groq_streaming_integration.py`.

---

## 2. Key Technical Changes

### A. Streaming Pipeline Orchestration (`the_relay/pipeline/orchestrator.py`)
- Created `StreamResultIterator` wrapping generator execution:
  - Implements `__iter__` and `__next__`.
  - Captures `StopIteration.value` upon generator completion and stores it in `stream.result`.
  - Enables idiomatic iteration via `for chunk in stream:`, `st.write_stream(stream)`, or `yield from stream`.
- Implemented `step_3_stream_reply(query, chunks, source)`:
  - If chunks are empty, immediately returns explicit refusal with null TTFT.
  - If passages exist, calls `client.stream_generate(...)` and yields each token chunk as it arrives from the provider.
- Implemented `run_request_stream(...)`:
  - Executes Step 1 (intent analysis) and Step 2 (hybrid passage retrieval).
  - Streams Step 3 synthesis tokens to callers in real time.
  - Automatically records `user_visible_ttft_ms` on the first emitted text chunk.
  - Executes Step 4 verification guard and factual grading upon stream completion.

### B. Groq Adapter Streaming Hardening (`the_relay/models/groq_client.py`)
- Standardized usage extraction from streaming chunks:
  - Cleanly tracks `actual_usage_in`, `actual_usage_out`, `actual_usage_tot` from any chunk carrying `chunk.usage` (`stream_options={"include_usage": True}`).
  - When present, maps to `actual_input_tokens`, `actual_output_tokens`, and `actual_total_tokens`.
  - Preserves `None` when usage is absent upstream.
- Hardened exception handling for streaming:
  - Added dedicated handlers for `groq.RateLimitError`, `groq.AuthenticationError`, `groq.APITimeoutError`, and `(groq.APIConnectionError, groq.InternalServerError, groq.APIStatusError)`.
  - Strips API keys (`gsk_...`), Bearer tokens, and sensitive headers via `sanitize_error(...)`.

### C. CLI Streaming Integration (`scripts/ask.py`)
- Added `--stream` CLI argument.
- When enabled, consumes `pipeline.run_request_stream(...)`, immediately flushing each token piece to `sys.stdout`.
- Prints comprehensive post-execution metrics from `stream.result`.

### D. Interactive Dashboard Updates (`dashboard/app.py`)
- Added real-time streaming toggle with `st.write_stream(stream)` and `stream.result` extraction.
- Fixed line 120 metric display:
  ```python
  ttft_str = f"{res.first_token_ms:.1f} ms" if res.first_token_ms is not None else "N/A"
  m2.metric("First Token (TTFT)", ttft_str)
  ```
  Preventing `TypeError` when TTFT is `None`.
- Updated retrieval box caption to accurately reflect Hybrid BM25 + Dense embeddings.

### E. Opt-In Live Test Safety (`tests/test_groq_live_opt_in.py`)
- Strict gate: skipped unless `RUN_LIVE_GROQ_TEST=1`, `CONFIRM_FREE_TIER=1`, and `AUTHORIZED=1` are explicitly present in the environment.
- Ordinary `pytest` and test runs make 0 live network calls.

---

## 3. Verification & Test Coverage

### Dedicated Phase 7 Test Suite (`tests/test_groq_streaming_integration.py` & `tests/test_groq_live_opt_in.py`)
1. `test_adapter_streaming_chunk_yield_and_ttft`: Verified chunk emission, first token timing, and usage footer extraction. (PASS)
2. `test_adapter_streaming_omitted_usage_preserves_null`: Verified null preservation when usage is omitted. (PASS)
3. `test_adapter_streaming_rate_limit_error`: Verified 429 error handling, header extraction, and key sanitization in streaming mode. (PASS)
4. `test_adapter_streaming_server_error`: Verified 500 error handling in streaming mode. (PASS)
5. `test_groq_missing_credentials_fails_safely`: Verified missing credentials raise safe `ValueError`. (PASS)
6. `test_stream_result_iterator_wrapper`: Verified iterator yields chunks and populates `.result`. (PASS)
7. `test_orchestrator_run_request_stream_success`: Verified orchestrator streaming end-to-end with citation verification and factual grading. (PASS)
8. `test_orchestrator_stream_retries_on_rate_limit_before_first_chunk`: Verified retry with exponential backoff if 429 occurs before first token. (PASS)
9. `test_zero_silent_fallback_on_groq_stream_error`: Verified immediate refusal on empty passages and zero silent fallback. (PASS)
10. `test_sanitize_error_comprehensive`: Verified redaction of API keys, Bearer tokens, and Authorization headers. (PASS)
11. `test_opt_in_live_groq_single_minimal_call`: Skipped safely by default. (SKIPPED)

**Result:** 10 passed, 1 skipped in 0.63s.

---

## 4. Acceptance Gate Checklist

- [x] Production Groq adapter integrated into full pipeline response path (`run_request_stream`).
- [x] True end-to-end streaming supported across adapter, orchestrator, CLI (`scripts/ask.py --stream`), and Web Dashboard (`dashboard/app.py`).
- [x] Provider TTFT and user-visible TTFT tracked and distinguished.
- [x] Structured usage metadata extracted from streaming chunks and propagated.
- [x] No silent fallbacks to stand-in or mock on Groq error.
- [x] Missing or invalid credentials fail safely without leaking keys.
- [x] Opt-in live test isolated and skipped by default.
- [x] Zero whitespace errors (`git diff --cached --check`).
