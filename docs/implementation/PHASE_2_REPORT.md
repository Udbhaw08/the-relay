# PHASE 2 IMPLEMENTATION REPORT: Independent A/B/C Experiments and Reproducibility

**Date:** 2026-11-12<br>
**Feature Branch:** `feat/the-relay-groq-hardening`<br>
**Target:** Experiment context isolation, quota reset guarantees, deterministic seeding, and experiment manifest provenance

---

## 1. Executive Summary

Phase 2 establishes strict independence and reproducibility across retrieval evaluation experiments (Settings A, B, and C). Previously, sequential execution of Settings A, B, and C against a shared StandInModelClient could allow earlier settings to exhaust rolling RPM limits, causing subsequent settings to encounter artificial rate-limiting and degradation.

To ensure fair and repeatable comparisons:
1. `StandInModelClient` now provides explicit `reset_quota_state()` to clear in-flight requests, sliding-window timestamps, and daily counters between evaluation runs.
2. An isolated, seeded pseudorandom generator (`random.Random(seed)`) guarantees deterministic simulation latency and fault outcomes across repeated runs.
3. `TrafficGenerator` resets quota and seeds before each retrieval setting benchmark.
4. Experiment execution records complete run provenance: `run_id`, Git commit SHA, configuration snapshots, and benchmark question lists are preserved in `data/runs/<run_id>/manifest.json`.
5. Degradation provenance is explicitly logged: when adaptive throttling reduces context to Setting A, both `requested_retrieval_setting` and `effective_retrieval_setting` are preserved alongside `degradation_reason = "rate_limit_adaptive_throttle"`.

---

## 2. Key Changes Implemented

### 2.1 Simulator Isolation & Seeding (`the_relay/models/stand_in.py`)
- Added `random_seed: Optional[int] = None` and `self._rng = random.Random(random_seed)`.
- Added `set_seed(seed: int)` and `reset_quota_state()` to eliminate cross-scenario contamination.
- Added `fast_mode: bool = False` to enable responsive, instant unit testing while preserving exact calibrated TTFT/total latency calculations.

### 2.2 Benchmarks Runner & Experiment Manifest (`scripts/run_benchmarks.py`)
- Added CLI arguments: `--run-id`, `--csv`, `--seed`, `--offline-only`.
- Implemented `save_run_manifest()` which writes an immutable experiment snapshot (`data/runs/<run_id>/manifest.json`) capturing:
  - Run ID and ISO-8601 UTC timestamp
  - Current Git commit SHA (`git rev-parse HEAD`)
  - Random seed
  - Configured LLM provider & Groq model
  - Full snapshot of `RETRIEVAL_SETTINGS`
  - Benchmark question IDs and count
  - Target CSV output path

### 2.3 Traffic Generator Quota Isolation (`the_relay/traffic/generator.py`)
- `run_retrieval_setting_benchmark()` resets quota state and assigns seed prior to executing each setting.
- All load scenario methods (`run_scenario_steady`, `run_scenario_burst`, etc.) accept `run_id` and pass it through to `RelayPipeline` and `ResultsLogger`.

### 2.4 Degradation Provenance (`the_relay/pipeline/orchestrator.py`, `the_relay/traffic/logger.py`)
- Added `degradation_reason: Optional[str] = None` to `PipelineResult`.
- When adaptive degradation occurs (`limit_warning=True` and `effective_setting != retrieval_setting`), `degradation_reason` is set to `"rate_limit_adaptive_throttle"`.
- `ResultsLogger` records `run_id`, `requested_retrieval_setting`, and `degradation_reason`.

---

## 3. Test & Verification Log

| Command | Exit Code | Observed Output / Result |
| :--- | :---: | :--- |
| `pytest -v tests/test_experiments_isolation.py` | 0 | 5 passed in 23.54s |
| `pytest -v` (full regression suite) | 0 | 47 passed in 63.96s |
| `git diff --check` | 0 | Clean (zero whitespace errors) |

---

## 4. Acceptance Gate Evaluation

- [x] A/B/C use identical benchmark question IDs and order.
- [x] Each setting starts with an independent limiter/retry/degradation state.
- [x] Setting A cannot exhaust shared quota before Setting B or C.
- [x] Requested and effective retrieval settings are logged distinctly.
- [x] Degradation reason is recorded on adaptive downscaling.
- [x] Fixed random seeds produce deterministic simulator behavior.
- [x] Repeated runs maintain distinct run IDs without collisions.
- [x] All 47 automated tests pass.
- [x] Phase report written.
