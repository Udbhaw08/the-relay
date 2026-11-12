# Phase 6 Implementation Report: Groq Rate Limiting, Quotas, Backoff, and Resilience

**Date:** 2026-11-12<br>
**Branch:** `feat/the-relay-groq-hardening`<br>
**Target Provider:** GroqCloud API (`api.groq.com/openai/v1`) with model `openai/gpt-oss-20b`<br>
**Official Groq Docs Source:** [https://console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) (Checked: November 12, 2026)<br>
**Test Suite Status:** 94 passed / 94 total (100% passing)

---

## 1. Executive Summary

Phase 6 implements production-grade rate limiting, quota management, exponential backoff, and failure resilience engineered specifically for GroqCloud's API semantics. The system enforces local safety caps, parses official provider headers, distinguishes transient from permanent failures, applies true full-jitter backoff, reconciles estimated token reservations with actual usage, and bounds concurrency to prevent thundering-herd cascading degradation.

---

## 2. Official Groq Rate-Limit Semantics and Documentation

Per the official Groq documentation ([Groq Rate Limits Documentation](https://console.groq.com/docs/rate-limits)), rate limits are governed by the following core architectural rules:

1. **Organization-Level Scope:** Rate limits on GroqCloud apply at the **Organization level**, not the individual API key level. If multiple applications, users, or experiments share an organization or API key, all calls draw from the same shared quota pool.
2. **Dimension Independence:** Groq tracks separate limits across multiple dimensions:
   - **RPM (Requests Per Minute):** Rate of incoming HTTP requests per rolling 60-second window.
   - **RPD (Requests Per Day):** Cumulative requests allowed per calendar day.
   - **TPM (Tokens Per Minute):** Aggregate token throughput per rolling 60-second window.
   - **TPD (Tokens Per Day):** Cumulative tokens allowed per calendar day.
   - **ITPM / OTPM:** Separate input token and output token throughput limits for high-throughput or reasoning models.
3. **Response Headers:**
   - `retry-after`: Seconds (or HTTP date) to wait before retrying when HTTP 429 is returned.
   - `x-ratelimit-limit-requests`: Maximum allowed requests in the active window.
   - `x-ratelimit-remaining-requests`: Remaining request quota in the active window.
   - `x-ratelimit-reset-requests`: Duration until the request window resets (e.g. `2s`, `1m30s`, `14m`).
   - `x-ratelimit-limit-tokens`: Maximum allowed tokens in the active window.
   - `x-ratelimit-remaining-tokens`: Remaining token quota in the active window.
   - `x-ratelimit-reset-tokens`: Duration until the token window resets.
   - `x-request-id`: Unique server-side identifier for tracing and telemetry.

---

## 3. Resilience Architecture & Implementation

### 3.1 Header Parsing & Structured State Extraction

In [the_relay/pipeline/resilience.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/pipeline/resilience.py):
- `parse_duration_string(val)`: Normalizes Groq's multi-unit duration strings (`2s`, `1m30s`, `500ms`, `1h`) into exact float seconds.
- `parse_retry_after(header_val, now_fn)`: Robustly parses numeric seconds, duration strings, and standard HTTP RFC date strings against an injectable clock.
- `extract_groq_rate_limit_state(headers)`: Maps incoming raw headers into a structured, type-safe `GroqRateLimitState` dataclass without leaking sensitive authorization credentials.

### 3.2 Error Classification: Transient vs. Permanent

`is_retryable_error(status, error_message, status_code)` prevents retry storms and thundering-herd resource exhaustion by strictly delineating failure types:
- **Non-Retryable (Fail Fast):**
  - Authentication errors (`401 Unauthorized`, `403 Forbidden`, invalid API key).
  - Invalid client requests (`400 Bad Request`, `404 Not Found`, `422 Unprocessable Entity`).
  - Daily quota exhaustion (`Daily budget exhausted`, `RPD limit reached`). Immediate retries cannot succeed and waste quota.
- **Retryable (Eligible for Backoff):**
  - Rate limits (`HTTP 429`, `status == "rate_limited"`).
  - Network timeouts (`HTTP 408`, `HTTP 504`, `status == "timeout"`).
  - Transient upstream server errors (`HTTP 500`, `HTTP 502`, `HTTP 503`, connection resets).

### 3.3 Truncated Exponential Backoff with True Full Jitter

In [the_relay/pipeline/resilience.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/pipeline/resilience.py), `compute_backoff` implements AWS/Google-standard true full jitter:
$$t_{\text{backoff}} = \text{uniform}\Big(0,\, \min(t_{\text{max}},\, t_{\text{base}} \times 2^{\text{attempt}})\Big)$$
- If the provider includes a `Retry-After` header, it is respected directly up to a safety cap (`MAX_RETRY_AFTER_CAP = 60.0s`) to prevent indefinite client hangs.
- Supports injectable random number generators (`rng`) and sleepers for 100% deterministic, zero-delay unit testing.

### 3.4 Local Rolling-Window Quota Limiter with Token Reconciliation

`LocalQuotaLimiter` enforces client-side safety caps before outbound requests are dispatched:
- **Rolling Windows:** Maintains timestamp deques for rolling 60-second windows for RPM and TPM. Entries older than 60 seconds are automatically expired.
- **Token Reservation:** When a request is queued, an initial token allocation is reserved based on prompt heuristics.
- **Token Reconciliation:** Once the model completes and actual provider usage is captured, `reconcile(reservation_id, actual_tokens)` reconciles the delta, freeing unused token capacity or adjusting daily usage.
- **Configurable Safety Caps:** Public base limits are never assumed to match the unverified friend account. Caps are configured via environment variables in [the_relay/config.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/config.py):
  - `LOCAL_RPM_LIMIT = 30`
  - `LOCAL_TPM_LIMIT = 30000`
  - `LOCAL_RPD_LIMIT = 14400`
  - `LOCAL_TPD_LIMIT = 500000`

### 3.5 Bounded Concurrency & Backpressure Controller

`BackpressureController` in [the_relay/pipeline/resilience.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/pipeline/resilience.py) prevents unbounded memory growth and resource collapse:
- Enforces `MAX_CONCURRENT_REQUESTS = 5` active in-flight executions.
- Enforces `MAX_QUEUE_CAPACITY = 50` pending queued requests.
- When capacity is exceeded, rejects requests immediately with `queue_capacity_breached_backpressure` instead of accumulating unbounded latency.

### 3.6 Stand-In Deterministic Fault Injection

In [the_relay/models/stand_in.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/models/stand_in.py):
- Added `inject_fault(fault_type)` supporting deterministic injection of `"429"`, `"timeout"`, `"network_failure"`, and `"500"`.
- Added `exhaust_rpm()`, `exhaust_tpm()`, and `exhaust_daily_budget()`.
- All simulator outcomes are explicitly stamped with `is_simulated = True`.

### 3.7 Dynamic Daily Exhaustion Notifications

`format_daily_exhaustion_message(reset_seconds)` replaces hardcoded "in 9 hours at 00:00 UTC" claims with dynamic reset durations extracted directly from provider headers (e.g. `x-ratelimit-reset-requests` or `Retry-After`), formatting precise hours and minutes when available.

---

## 4. Test Suite and Verification

12 dedicated unit and integration tests were added in [tests/test_resilience_and_quotas.py](file:///c:/Users/udbha/Desktop/aivoice/tests/test_resilience_and_quotas.py):
1. `test_parse_duration_strings`: Validates parsing of `2s`, `1m30s`, `500ms`, `2h`, `1h15m30s`.
2. `test_parse_retry_after`: Validates numeric seconds, duration strings, and RFC HTTP date strings.
3. `test_extract_groq_rate_limit_state`: Validates extraction of all Groq rate-limit headers.
4. `test_full_jitter_backoff_bounds_and_caps`: Validates backoff bounds, true full-jitter uniform distribution, and safety caps.
5. `test_error_classifier`: Validates transient (retryable) vs permanent (non-retryable) error classifications.
6. `test_local_quota_rpm_rolling_window`: Validates rolling 60-second window expiry and rate limiting.
7. `test_local_quota_tpm_reservation_and_reconciliation`: Validates token reservation and actual post-response reconciliation.
8. `test_daily_budget_exhaustion_and_notice`: Validates daily budget denial and dynamic reset notice formatting.
9. `test_deterministic_pipeline_retry_with_injected_sleeper`: Validates pipeline retry loop with mock sleeper and Retry-After header.
10. `test_non_retryable_auth_and_daily_budget_fail_fast`: Validates immediate fail-fast on 401 unauthorized.
11. `test_bounded_concurrency_and_backpressure`: Validates bounded concurrency and queue rejection under overload.
12. `test_stand_in_deterministic_fault_injection`: Validates deterministic injection of 429, timeout, and 500 errors in simulator.

### Full Test Suite Run:
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-8.3.4, pluggy-1.6.0
collected 94 items

tests/test_csv_schema_and_aggregation.py ...........                     [ 11%]
tests/test_experiments_isolation.py .....                                [ 17%]
tests/test_factual_evaluation.py ...............                         [ 32%]
tests/test_groq_client.py ....................                           [ 54%]
tests/test_ingestion.py ...                                              [ 57%]
tests/test_pipeline.py ..                                                [ 59%]
tests/test_resilience_and_quotas.py ............                         [ 72%]
tests/test_retrieval.py ............                                     [ 85%]
tests/test_stand_in.py ...                                               [ 88%]
tests/test_telemetry_accuracy.py ...........                             [100%]

======================= 94 passed in 189.01s (0:03:09) ========================
```

---

## 5. Phase Acceptance Gate Checklist

- [x] Official Groq rate-limit headers and semantics consulted and documented.
- [x] Header parsing handles numeric, duration strings (`2s`, `1m30s`), and HTTP dates.
- [x] RPM, TPM, RPD, and TPD distinguished with configurable local safety caps.
- [x] True full jitter implemented: `uniform(0, min(max_backoff, base * 2**attempt))`.
- [x] Retry-After header respected subject to configurable safety cap (`MAX_RETRY_AFTER_CAP = 60s`).
- [x] Non-retryable permanent errors (401, 403, 400, 404, 422, daily exhaustion) fail fast without retry loops.
- [x] Token reservation before dispatch reconciles with actual provider usage after completion.
- [x] Concurrency and pending queue bounded with backpressure rejection.
- [x] Stand-In supports deterministic fault injection for 429, timeout, network failure, 500, RPM, TPM, and daily exhaustion.
- [x] All 94 unit and integration tests passing.
- [x] Phase report written and committed.
