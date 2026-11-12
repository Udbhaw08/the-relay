# Phase 8 Report: Load Generator, Scenarios, and Reproducible Benchmark Execution

**Date:** 2026-11-12
**Branch:** `feat/the-relay-groq-hardening`
**Execution Status:** Completed

---

## 1. Executive Summary

Phase 8 hardens synthetic traffic generation, scenario pacing, admission accounting, bounded queue backpressure, and run-scoped benchmark logging. It ensures that all five required load scenarios strictly adhere to their intended arrival semantics and produce reproducible, mathematically validated experimental data without corrupting historical benchmarks.

Phase 8 delivers:
1. **Paced Steady Load Arrival Scheduling:** Replaced post-request sleep with strict start-to-start target interval scheduling (`schedule_start + i * interval`), eliminating inter-arrival drift and guaranteeing an unyielding offered traffic rate.
2. **Comprehensive Admission Accounting:** Enhanced `ConcurrencyTracker` to record offered, submitted, accepted, rejected, successful, and failed request counts across burst and sustained load scenarios.
3. **Bounded Queue Capacity and Backpressure Rejection:** Enforced hard caps on queue capacity (e.g. max queue depth of 15-20) and in-flight concurrency (e.g. 5-10 concurrent workers), rejecting excess requests with explicit backpressure (`degradation_reason="queue_capacity_breached_backpressure"`) rather than letting queues grow unbounded.
4. **Fast-Failing Daily Budget Exhaustion:** Confirmed that requests encountering an exhausted daily quota fail fast with zero retries, avoiding pointless retry loops while delivering graceful notices and reset calculations.
5. **Run-Scoped Reproducibility & Manifest Snapshots:** Automated immutable `manifest.json` generation capturing run ID, Git commit SHA, random seed, provider/model settings, execution duration, and scenario accounting summaries.
6. **Isolated Experimentation & Clean Denominators:** Preserved strict scenario-only filtering in table computation, ensuring retrieval benchmarks (Settings A, B, C) and load scenarios never contaminate each other's metrics.

---

## 2. Key Technical Changes

### A. Start-to-Start Paced Steady Load (`the_relay/traffic/generator.py`)
- Paced scheduling:
  ```python
  schedule_start_perf = time.perf_counter()
  for i in range(num_requests):
      target_start = schedule_start_perf + (i * target_interval)
      wait_for_slot = target_start - time.perf_counter()
      if wait_for_slot > 0:
          time.sleep(wait_for_slot)
  ```
- Guaranteed that requests are offered at predictable intervals regardless of individual request execution durations.

### B. ConcurrencyTracker & Admission Accounting (`the_relay/traffic/generator.py`)
- Added synchronized fields and methods tracking:
  - `offered_count`: Total requests intended to be sent.
  - `submitted_count`: Requests successfully enqueued.
  - `accepted_count`: Requests dequeued into active concurrency.
  - `rejected_count`: Requests rejected by queue backpressure.
  - `successful_count`: Requests completed with `status == "ok"`.
  - `failed_count`: Requests terminated with `status != "ok"`.
  - `max_concurrency` and `peak_queue_depth`.
- If a task arrives when `_queue_depth >= max_queue`, it is rejected immediately with `degradation_reason="queue_capacity_breached_backpressure"`.

### C. Run Manifest Snapshots (`scripts/run_benchmarks.py`)
- Created `save_run_manifest` and `update_run_manifest`:
  - Records experiment metadata into `data/runs/<run_id>/manifest.json`.
  - Captures Git commit SHA, random seeds, provider/model parameters, start and end timestamps, total execution duration, and scenario accounting summaries.

### D. Table Generation with Explicit Run Filtering (`scripts/compute_tables.py`)
- Validated that `generate_table_2a_and_2b(df, run_id=...)` and `generate_table_3(df, run_id=...)` strictly filter rows by `run_id`.
- Latency percentiles computed exclusively over valid positive samples (`first_token_ms > 0` and `total_ms > 0` on successful requests with output tokens).

---

## 3. Verification & Test Coverage

### Dedicated Phase 8 Test Suite (`tests/test_load_scenarios_and_benchmarks.py`)
1. `test_steady_start_to_start_pacing`: Verified start-to-start inter-arrival scheduling without drift. (PASS)
2. `test_concurrency_tracker_admission_accounting`: Verified admission, queue tracking, and accounting counters. (PASS)
3. `test_burst_scenario_accounting_and_backpressure`: Verified offered vs accepted vs rejected accounting during burst load. (PASS)
4. `test_sustained_overload_scenario`: Verified bounded concurrency and queue depth caps under sustained load. (PASS)
5. `test_per_minute_limit_halved_scenario`: Verified 50% RPM reduction and throttling. (PASS)
6. `test_daily_budget_exhaustion_scenario_zero_retries`: Verified zero retry loop on daily budget exhaustion. (PASS)
7. `test_run_manifest_metadata_and_update`: Verified immutable manifest generation and accounting updates. (PASS)
8. `test_table_2_and_3_with_run_scoped_data`: Verified run-scoped isolation and markdown table generation. (PASS)

---

## 4. Acceptance Gate Checklist

- [x] All 5 required load scenarios preserved and accurately scheduled.
- [x] Steady load uses start-to-start target interval pacing.
- [x] Burst scenario records offered, submitted, accepted, rejected, successful, and failed counts.
- [x] Sustained overload enforces bounded queue capacity and backpressure rejection.
- [x] Daily budget exhaustion fails fast with zero retries.
- [x] Run manifest records Git commit, seeds, run ID, timestamps, and accounting metrics.
- [x] Strict scenario-only and run-scoped filtering prevents cross-scenario contamination.
- [x] Zero whitespace errors (`git diff --cached --check`).
