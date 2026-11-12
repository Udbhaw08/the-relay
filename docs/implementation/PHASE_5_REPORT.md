# Phase 5 Implementation Report: Accurate Latency, TTFT, Token, Queue, and Cost Telemetry

**Date:** 2026-11-12<br>
**Branch:** `feat/the-relay-groq-hardening`<br>
**Target Provider:** GroqCloud (`api.groq.com/openai/v1`) with model `openai/gpt-oss-20b`<br>
**Test Suite Status:** 82 passed / 82 total (100% passing)

---

## 1. Executive Summary

Phase 5 addresses the critical requirement of replacing synthetic, guessed, or conflated performance metrics with accurately measured and labelled telemetry. Prior to Phase 5:
1. Failed, rate-limited, or timed-out requests recorded fabricated TTFT values (e.g. `10.0ms` or `0.0ms` in `stand_in.py`, or `total_ms` in `groq_client.py`).
2. Duration measurements relied on wall-clock epoch subtractions rather than monotonic timers.
3. Token usage numbers conflated heuristic word-count estimates with actual hardware provider token counts.
4. Peak queue length was computed via an ungrounded heuristic formula (`reqs_sent // 3`) rather than measured queue depth.
5. Economic cost was hardcoded as `"$0.00 (Free Tier)"` regardless of actual usage or unverified rate cards.

Phase 5 rectifies all of these telemetry deficiencies:
- `ModelResponse.first_token_ms` and `PipelineResult.first_token_ms` are strictly `Optional[float] = None`, recording `None` whenever no non-empty text chunk was emitted.
- All elapsed durations are calculated using monotonic high-resolution clocks (`time.perf_counter()`), measuring retrieval, generation, verification, and queue wait times independently.
- Actual provider token usage (`actual_input_tokens`, `actual_output_tokens`, `actual_total_tokens`) is recorded strictly from provider usage metadata when returned, leaving them `None` when unavailable, and keeping heuristic estimates (`estimated_*`) in dedicated distinct fields.
- Queue depth (requests waiting for admission) is tracked independently from in-flight concurrency (requests actively executing).
- Hardcoded `$0.00` cost claims are completely eliminated, reporting `"N/A (Free Tier / unbilled)"` unless a verified commercial rate card exists.
- Percentile calculations in Table 2a, 2b, and 3 strictly filter for valid successful samples (`status == "ok"` and `tokens_out > 0`), reporting `"N/A"` when zero valid samples exist.

---

## 2. Telemetry Architecture & Implementation Details

### 2.1 Strictly Nullable True TTFT

True Time-To-First-Token (TTFT) represents the elapsed latency from request submission to the arrival of the first non-empty text chunk emitted by the model.
- In [the_relay/models/base.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/models/base.py), `ModelResponse.first_token_ms` was changed from `float` to `Optional[float] = None`.
- In [the_relay/models/stand_in.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/models/stand_in.py):
  - Removed all `first_token_ms=10.0` or `first_token_ms=total_ms` assignments on rate limits, timeouts, or simulated 500 server errors. On all non-ok outcomes, `first_token_ms` is strictly `None`.
- In [the_relay/models/groq_client.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/models/groq_client.py):
  - In `generate()`: On all error paths (`RateLimitError`, `AuthenticationError`, `APITimeoutError`, `InternalServerError`, `APIStatusError`, `Exception`), `first_token_ms` is strictly `None`.
  - In `stream_generate()`: If the stream finishes or aborts before yielding any non-empty text chunk, `first_token_ms` is strictly `None`.
- In [the_relay/pipeline/orchestrator.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/pipeline/orchestrator.py):
  - Immediate refusals where no model call occurred record `first_token_ms = None`.
  - For all completed pipeline results, `effective_ttft = resp.first_token_ms if (resp.status == "ok" and resp.tokens_out > 0) else None`.

### 2.2 Monotonic Clock & Component Timing Breakdown

Wall-clock subtractions (`time.time()`) are vulnerable to system clock adjustments, NTP slew, and drift.
- All elapsed intervals in the pipeline now use `time.perf_counter()`:
  - `retrieval_ms`: High-resolution duration from retrieval start to finish.
  - `generation_ms`: High-resolution duration from model dispatch to completion.
  - `verification_ms`: High-resolution duration from citation verification start to finish.
  - `processing_ms`: Total internal processing elapsed time.
  - `total_wall_ms`: Monotonic end-to-end elapsed duration.
  - `timestamps`: Structured dictionary capturing monotonic checkpoint timestamps (`request_start_perf`, `attempt_N_retrieval_start/end`, `attempt_N_generation_start/end`, `attempt_N_verification_start/end`, `completion_perf`).

### 2.3 Strict Separation of Actual vs. Estimated Tokens

Token accounting never conflates provider hardware tokens with heuristic token estimates:
- `actual_input_tokens`: Captured directly from `completion.usage.prompt_tokens` if provided by GroqCloud. Set to `None` if the provider omits usage or when running offline under simulator mode.
- `actual_output_tokens`: Captured directly from `completion.usage.completion_tokens`.
- `actual_total_tokens`: Captured directly from `completion.usage.total_tokens`.
- `estimated_input_tokens`: Heuristic calculation (`len(prompt.split()) * 4 // 3`).
- `estimated_output_tokens`: Heuristic calculation (`len(completion.split()) * 4 // 3`).
- `estimated_total_tokens`: Sum of heuristic estimated input and output tokens.
- `is_simulated`: Boolean flag (`True` for Stand-In simulator, `False` for real Groq API calls).

### 2.4 Independent Queue Depth and In-Flight Concurrency

Queue depth and active concurrency represent fundamentally different states in distributed serving systems:
- `queue_depth`: Number of submitted requests waiting in the executor backlog for an available worker thread.
- `in_flight` (concurrency): Number of requests actively executing across worker threads.
- `peak_queue_depth`: Maximum backlog queue depth observed during the run.
- `max_concurrency`: Maximum active parallel worker threads observed during the run.
- `queue_wait_ms`: Measured time spent by a request in the queue prior to worker execution.

Implemented `ConcurrencyTracker` in [the_relay/traffic/generator.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/traffic/generator.py) to measure `queue_wait_ms`, `queue_depth`, and `concurrency` accurately in burst and sustained overload scenarios.

In [scripts/compute_tables.py](file:///c:/Users/udbha/Desktop/aivoice/scripts/compute_tables.py), the legacy heuristic `reqs_sent // 3` was removed. If queue depth telemetry is recorded in the CSV, its maximum is displayed; if not measured (such as in legacy baseline runs), it is reported honestly as `"N/A (not measured)"`.

### 2.5 Cost Telemetry & Unbilled Free-Tier Handling

In [scripts/compute_tables.py](file:///c:/Users/udbha/Desktop/aivoice/scripts/compute_tables.py), hardcoded `"$0.00 (Free Tier)"` output was removed. While developer accounts operate under free promotional tiers, claiming $0.00 cost implies zero economic resource consumption. Without an explicit, verified commercial contract or rate card, Table 2b reports `"N/A (Free Tier / unbilled)"`.

### 2.6 Percentile Aggregation Integrity

Percentile calculations in Table 2a, Table 2b, and Table 3 follow rigorous data filtering:
- TTFT percentiles ($p_{50}, p_{95}, p_{99}$) are calculated strictly over successful requests with positive output tokens:
  $$\text{valid\_ttft} = \text{subset}[\text{status} == \text{"ok"} \land \text{tokens\_out} > 0 \land \text{first\_token\_ms} > 0]$$
- Successful total latency percentiles are calculated strictly over $\text{subset}[\text{status} == \text{"ok"}]$.
- If $N_{\text{valid}} = 0$ (e.g. `daily_budget_exhausted` where 100% of requests are rate limited), Table 2a outputs `"N/A"` rather than fabricating `0.0ms` or reporting error-response latencies.

### 2.7 Backwards Compatibility & Extended CSV Schema

The CSV schema in [the_relay/traffic/schema.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/traffic/schema.py) and logger in [the_relay/traffic/logger.py](file:///c:/Users/udbha/Desktop/aivoice/the_relay/traffic/logger.py) support all extended telemetry columns while preserving complete backwards compatibility:
- Historical 125-row `results.csv` validates with zero errors.
- New optional columns (`actual_input_tokens`, `actual_output_tokens`, `actual_total_tokens`, `estimated_input_tokens`, `estimated_output_tokens`, `estimated_total_tokens`, `is_simulated`, `retrieval_ms`, `generation_ms`, `verification_ms`, `queue_wait_ms`, `processing_ms`, `total_wall_ms`, `queue_depth`, `concurrency`) are validated when present.

---

## 3. Verification & Test Suite

11 new automated unit and integration tests were added in [tests/test_telemetry_accuracy.py](file:///c:/Users/udbha/Desktop/aivoice/tests/test_telemetry_accuracy.py):
1. `test_null_ttft_on_stand_in_failures`: Validates null TTFT on stand-in rate limits, daily budget exhaustion, timeouts, and 500 errors.
2. `test_null_ttft_on_groq_failures`: Validates null TTFT on Groq 429, 401, and timeout exceptions.
3. `test_streaming_null_ttft_when_no_text_chunks_yielded`: Validates null TTFT when a stream yields empty chunks.
4. `test_monotonic_pipeline_timings_and_component_breakdown`: Validates monotonic timestamp progression and non-negative component durations.
5. `test_queue_depth_distinct_from_in_flight`: Validates independent tracking of queue depth and concurrency.
6. `test_actual_and_estimated_tokens_separation_groq`: Validates capture of provider usage tokens without conflation.
7. `test_actual_tokens_null_when_missing_and_stand_in_simulated`: Validates null actual tokens when usage is omitted and stand-in `is_simulated` provenance.
8. `test_cost_never_hardcoded_to_zero`: Validates elimination of `"$0.00"` cost strings in aggregated output.
9. `test_percentile_calculations_handle_failed_and_empty`: Validates `compute_percentiles` resilience on empty, zero, or negative series.
10. `test_failed_requests_excluded_from_latency_percentiles`: Validates that failed 429 requests do not contaminate successful latency percentiles.
11. `test_csv_schema_validates_extended_telemetry_columns`: Validates schema parsing and range bounds for all extended telemetry columns.

### Full Test Suite Run:
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-8.3.4, pluggy-1.6.0
collected 82 items

tests/test_csv_schema_and_aggregation.py ...........                     [ 13%]
tests/test_experiments_isolation.py .....                                [ 19%]
tests/test_factual_evaluation.py ...............                         [ 37%]
tests/test_groq_client.py ....................                           [ 62%]
tests/test_ingestion.py ...                                              [ 65%]
tests/test_pipeline.py ..                                                [ 68%]
tests/test_retrieval.py ............                                     [ 82%]
tests/test_stand_in.py ...                                               [ 86%]
tests/test_telemetry_accuracy.py ...........                             [100%]

======================== 82 passed in 99.45s (0:01:39) ========================
```

---

## 4. Phase Acceptance Gate Checklist

- [x] All elapsed timings use monotonic clocks (`time.perf_counter()`).
- [x] TTFT is strictly `None` when no model text chunk was emitted.
- [x] Component durations (retrieval, generation, verification, queue wait) measured separately.
- [x] Actual provider tokens separated from heuristic estimates; actual tokens null when omitted.
- [x] Queue depth tracked independently from active concurrency; heuristic `reqs // 3` eliminated.
- [x] Hardcoded `"$0.00"` cost claims eliminated; unbilled free tier reported honestly.
- [x] Latency percentiles computed strictly over valid successful samples ($N_{\text{valid}} > 0$).
- [x] Simulator latency and token records explicitly marked with `is_simulated = True`.
- [x] Full backwards compatibility maintained with historical 125-row `results.csv`.
- [x] All 82 unit and integration tests passing.
- [x] Phase report written and committed.
