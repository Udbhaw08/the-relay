# PHASE 1 IMPLEMENTATION REPORT: CSV Schema, Aggregation, and Report Calculation Correctness

**Date:** 2026-11-12<br>
**Feature Branch:** `feat/the-relay-groq-hardening`<br>
**Target:** Elimination of cross-scenario data contamination, CSV schema enforcement, and mathematical calculation accuracy

---

## 1. Executive Summary

Phase 1 resolves the data aggregation defects in the benchmark telemetry pipeline. In particular, the critical flaw where retrieval evaluation grouping in `scripts/compute_tables.py` used an `OR` condition (`(retrieval_setting == s_key) | (scenario == eval_s_key)`) has been eliminated. That defect previously caused dozens of load-test requests degraded to `setting_a` to be conflated with the 15 benchmark evaluation questions, artificially reporting 73 questions in Setting A and 43 in Setting B.

Following Phase 1 corrections, each retrieval setting evaluates strictly against its designated scenario (`eval_setting_a`, `eval_setting_b`, `eval_setting_c`), producing exactly 15 questions per setting from the verified 125-row historical dataset. A formal schema validator (`the_relay/traffic/schema.py`) has been implemented to validate column requirements, categorical domains, numeric ranges, duplicate request IDs within runs, and benchmark question integrity.

---

## 2. Key Changes Implemented

### 2.1 Formal CSV Schema & Validation (`the_relay/traffic/schema.py`)
- Defined `REQUIRED_COLUMNS` (`request_id`, `scenario`, `source`, `start_time`, `first_token_ms`, `total_ms`, `status`, `retries`, `tokens_in`, `tokens_out`, `retrieval_setting`, `answer_grade`).
- Added forward-compatible optional columns: `run_id`, `requested_retrieval_setting`.
- Enforced strict domains:
  - Statuses: `{"ok", "rate_limited", "timeout", "error"}`
  - Answer Grades: `{"correct", "partially_correct", "wrong", "refused_correctly", "refused_wrongly", "error", "rate_limited", "unscorable"}`
  - Retrieval Settings: `{"setting_a", "setting_b", "setting_c"}`
- Implemented `validate_results_dataframe()` to verify types, positive timestamps, non-negative tokens/latencies, within-run request ID uniqueness, and question ID alignment with `EXPECTED_BENCHMARK_QUESTION_IDS`.

### 2.2 Table Aggregator Math Corrections (`scripts/compute_tables.py`)
- **Strict Scenario Filtering in Table 3:** Retrieval evaluation rows are grouped strictly by `df["scenario"] == f"eval_{s_key}"` (and optional `run_id`), preventing load-test rows from leaking into Table 3.
- **Accurate Denominators:** Denominators for answer accuracy reflect evaluated questions. Infrastructure failures (`status != "ok"`) are separated from factual answer accuracy and no longer count as wrong answers.
- **Null TTFT Handling:** Failed requests and requests generating 0 output tokens (e.g. `daily_budget_exhausted`) yield `N/A` for TTFT percentiles instead of fabricated synthetic placeholders (such as 10.0 ms).
- **Graceful Empty Groups:** When zero records exist for a setting or scenario, the table outputs `N/A` with sample count 0, preventing division-by-zero crashes or misleading zero values.
- **CLI Options:** Added `--csv`, `--run-id`, and `--validate` arguments.

### 2.3 Pipeline & Logger Enhancements (`the_relay/pipeline/orchestrator.py`, `the_relay/traffic/logger.py`)
- Added `run_id` and `requested_retrieval_setting` to `PipelineResult` and `ResultsLogger`.
- Ensured `ResultsLogger` detects existing file header format to preserve backwards compatibility with historical 12-column `results.csv`.
- Rate-limited and non-retryable failures record `status = resp.status`, `first_token_ms = None`, and `answer_grade = "error"|"refused_correctly"`, preventing infrastructure failures from being marked as factual errors.

---

## 3. Results Verification: Corrected Tables

Running `python scripts/compute_tables.py --validate` over the 125-row historical dataset yields:

### Table 2a (Summary):
- `steady` (real, 10 reqs): First token p50/p95 = 2352.4 / 2668.0 ms, Total p50/p95 = 2353.2 / 2666.5 ms.
- `burst` (stand-in, 20 reqs): First token p50/p95 = 1013.6 / 1359.8 ms, Total p50/p95 = 10.0 / 1181.5 ms.
- `sustained_overload` (stand-in, 25 reqs): First token p50/p95 = 1450.2 / 1858.4 ms, Total p50/p95 = 10.0 / 2353.3 ms.
- `per_minute_limit_halved` (stand-in, 15 reqs): First token p50/p95 = 1364.8 / 1927.3 ms, Total p50/p95 = 1873.1 / 2581.5 ms.
- `daily_budget_exhausted` (stand-in, 10 reqs): First token = **N/A** (0 output tokens; no fake 10.0 ms), Total p50/p95 = 10.0 / 10.0 ms.

### Table 3 (Corrected Retrieval Settings):
| Setting | Questions Asked | Correct & Cited % | Wrong % | Correctly Refused % | Tokens/Answer | First Token p50/p95 | Total Time p50/p95 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Piece size 250, 3 fetched, re-rank: no | **15** | 80.0% | 0.0% | 20.0% | 36.6 | 1299.8 / 1794.8 ms | 1802.1 / 2354.8 ms |
| Piece size 500, 5 fetched, re-rank: yes | **15** | 73.3% | 6.7% | 13.3% | 36.9 | 1257.8 / 1539.1 ms | 1884.3 / 2227.6 ms |
| Piece size 1000, 7 fetched, re-rank: yes | **15** | 73.3% | 6.7% | 20.0% | 35.4 | 1152.1 / 1558.0 ms | 1703.6 / 2132.2 ms |

*Note: All three settings now correctly report 15 evaluated benchmark questions without load-test contamination.*

---

## 4. Test & Verification Log

| Command | Exit Code | Observed Output / Result |
| :--- | :---: | :--- |
| `pytest -v tests/test_csv_schema_and_aggregation.py` | 0 | 11 passed in 4.27s |
| `pytest -v` (full regression suite) | 0 | 42 passed in 41.59s |
| `python scripts/compute_tables.py --validate` | 0 | Validation PASSED; Tables 1, 2a, 2b, 3 printed cleanly |
| `git diff --check` | 0 | Clean (zero whitespace errors) |

---

## 5. Acceptance Gate Evaluation

- [x] All summary tables are reproducible from validated CSV data.
- [x] Table 3 has correct scenario-only grouping (15 questions each; no load-test leak).
- [x] Missing columns, duplicate IDs within run, and invalid values caught by validator.
- [x] Failed requests have null TTFT (rendered as N/A).
- [x] Failed requests excluded from answer-accuracy denominators.
- [x] All 42 unit and integration tests pass.
- [x] Phase report written.
