# The Relay — Final Engineering Implementation & Validation Report

**Project:** The Relay — Resilient Research Paper Assistant
**Repository:** [https://github.com/Udbhaw08/the-relay](https://github.com/Udbhaw08/the-relay)
**Branch:** `feat/the-relay-groq-hardening`
**Author:** Udbhaw Anand
**Date of Completion:** November 13, 2026
**Final Validation Run ID:** `phase9_final_eval` (Benchmark seed 42)

---

## 1. Executive Summary

This report documents the autonomous execution, verification, and hardening of **The Relay** across all 10 planned phases (Phase 0 through Phase 9) as specified in `the_relay_autonomous_phase_execution_plan.md`.

The system implements a production-grade, 4-step decoupled agentic pipeline designed to answer technical queries over three arXiv research papers (*Attention Is All You Need*, *Moshi*, and *Dynamic Chunking for H-Net*). GroqCloud API (`api.groq.com/openai/v1`) using model `openai/gpt-oss-20b` was established as the sole supported real LLM provider, with legacy Gemini, xAI Grok, and NVIDIA NIM dependencies fully excised. All benchmark executions, rate-limiting stress tests, and retrieval setting evaluations were executed with complete experiment isolation, strict token provenance, zero silent fallback, and deterministic reproducibility.

---

## 2. Complete Phase Execution & Traceability Matrix

| Phase | Title | Commit SHA | Remote Push | Tests Passing | Key Artifacts |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **0** | Baseline Verification & Safety Pre-Conditions | `403cfb3` | Pushed | 31 passed | `docs/implementation/PHASE_0_REPORT.md`, `tests/test_groq_client.py` |
| **1** | Canonical CSV Schema & Historical Aggregation | `2dc3fdd` | Pushed | 42 passed | `the_relay/traffic/schema.py`, `scripts/compute_tables.py`, `tests/test_csv_schema_and_aggregation.py` |
| **2** | Independent Experiments & Quota Isolation | `9ed2833` | Pushed | 47 passed | `the_relay/eval/benchmark_questions.py`, `tests/test_experiments_isolation.py` |
| **3** | Provider Hardening & Factual Grounding | `c2a298e` | Pushed | 61 passed | `the_relay/eval/factual_grader.py`, `tests/test_factual_evaluation.py` |
| **4** | True Hybrid Retrieval Engine | `020061b` | Pushed | 70 passed | `the_relay/retrieval/engine.py`, `the_relay/retrieval/embeddings.py`, `tests/test_retrieval.py` |
| **5** | Telemetry Accuracy & Monotonic Timing | `be4af8a` | Pushed | 81 passed | `the_relay/pipeline/orchestrator.py`, `tests/test_telemetry_accuracy.py` |
| **6** | Groq Resilience, Rate Limiting & Backoff | `4f556d1` | Pushed | 95 passed | `the_relay/pipeline/resilience.py`, `tests/test_resilience_and_quotas.py` |
| **7** | Streaming Integration & Groq Adapter | `bf55799` | Pushed | 105 passed | `the_relay/models/groq_client.py`, `scripts/ask.py`, `dashboard/app.py`, `tests/test_groq_streaming_integration.py` |
| **8** | Load Generator & Reproducible Scenarios | `e60f460` | Pushed | 113 passed | `the_relay/traffic/generator.py`, `scripts/run_benchmarks.py`, `tests/test_load_scenarios_and_benchmarks.py` |
| **9** | End-to-End Validation, Report & Handoff | *Current* | *Pending push* | 112 passed, 1 skipped | `docs/SUBMISSION_REPORT.md`, `README.md`, `docs/implementation/FINAL_REPORT.md` |

---

## 3. Architecture & Core Pipeline Verification

### 3.1 Four-Step Decoupled Pipeline
1. **Step 1: Query Parser & Decomposer** (`the_relay/pipeline/orchestrator.py`):
   - Normalizes queries, extracts token entities, maps hints to target papers (*Attention*, *Moshi*, *Dynamic Chunking*), and detects out-of-scope queries (e.g. quantum annealing, Llama-3 infra, hospital DNA cohorts).
2. **Step 2: Passage Retrieval Tool** (`the_relay/retrieval/engine.py`):
   - Ingests all 3 arXiv PDFs without content fabrication:
     - `1706.03762v7.pdf`: 15 pages
     - `2410.00037v1.pdf`: 66 pages
     - `2507.07955v2.pdf`: 39 pages
   - True hybrid retrieval combines BM25Okapi lexical matching with dense SentenceTransformer vector search via Reciprocal Rank Fusion (RRF, $k=60$).
   - Persistent disk-cached embeddings with SHA-256 chunk hash invalidation.
   - Dynamic degradation to Setting A upon upstream rate limits.
3. **Step 3: Synthesis & Citation Drafter** (`the_relay/pipeline/orchestrator.py`, `the_relay/models/groq_client.py`):
   - Supports both synchronous generation and end-to-end token streaming (`step_3_stream_reply`).
   - Captures provider TTFT and user-visible first token arrival distinctly.
   - Extracts exact streaming usage metadata (`prompt_tokens`, `completion_tokens`, `total_tokens`) from SSE chunk footers (`include_usage=True`).
   - Zero silent fallback: failures raise explicit errors rather than substituting stand-in responses.
4. **Step 4: Citation Verification & Factual Guard** (`the_relay/eval/factual_grader.py`, `the_relay/retrieval/verifier.py`):
   - Validates that every bracketed citation `[Paper, Page X, Section Y]` maps to an indexed paper, resolves to valid page boundaries, and contains overlapping n-gram evidence.
   - Factual grading classifies outcomes into: `correct`, `partially_correct`, `wrong`, `refused_correctly`, `refused_wrongly`, `rate_limited`, `error`, `unscorable`.

---

## 4. Test Suite Summary

- **Total Test Cases:** 113 collected items
- **Passed:** 112 tests
- **Skipped:** 1 test (`tests/test_groq_live_opt_in.py::test_live_groq_opt_in_smoke` — skipped by default to protect API quotas; runs only with `--confirm-free-tier --authorized`)
- **Failed / Blocked:** 0
- **Execution Command:** `pytest -v`

### Key Areas Tested:
- CSV Schema validation and read-only aggregation idempotence (`test_csv_schema_and_aggregation.py`)
- Quota isolation and seed determinism across Settings A/B/C (`test_experiments_isolation.py`)
- Evidence-based factual grading and citation resolution (`test_factual_evaluation.py`)
- Groq client error handling, HTTP 429 backoff, and secret scrubbing (`test_groq_client.py`)
- Streaming chunk iteration and token extraction (`test_groq_streaming_integration.py`)
- Ingestion of all three PDFs (`test_ingestion.py`)
- Start-to-start pacing, burst queue accounting, bounded queue backpressure, and daily budget reset (`test_load_scenarios_and_benchmarks.py`)
- Telemetry accuracy, monotonic timing separation, and token provenance (`test_telemetry_accuracy.py`)

---

## 5. Benchmark Execution & Validated Data

- **Run ID:** `phase9_final_eval`
- **Output CSV:** `data/runs/phase9_final_eval/results.csv`
- **Manifest:** `data/runs/phase9_final_eval/manifest.json`
- **Random Seed:** 42
- **Duration:** 514.9s
- **Total Requests Evaluated:** 125 requests
  - Steady: 10 requests (paced at 1.0s target start-to-start intervals)
  - Setting A: 15 benchmark questions
  - Setting B: 15 benchmark questions
  - Setting C: 15 benchmark questions
  - Burst: 20 concurrent requests
  - Sustained Overload: 25 requests across 5 worker threads (bounded queue depth = 15)
  - Per-Minute Limit Halved: 15 requests
  - Daily Budget Exhausted: 10 requests (0 retries, immediate graceful notice)

### Summary Tables:
All tables were generated directly from `data/runs/phase9_final_eval/results.csv` via `scripts/compute_tables.py` and are embedded verbatim in [`docs/SUBMISSION_REPORT.md`](file:///c:/Users/udbha/Desktop/aivoice/docs/SUBMISSION_REPORT.md).

---

## 6. Groq Provider & Key Safety Status

1. **Configured Model:** `openai/gpt-oss-20b` via `https://api.groq.com/openai/v1`.
2. **Decommissioned Models Handled:** `llama-3.3-70b-versatile` was flagged as retired (August 16, 2026) and replaced with `openai/gpt-oss-20b`.
3. **Authorization & Free Tier Status:** The friend's key authorization and Free-tier status remain `UNVERIFIED`.
4. **Safety Rule Compliance:** Live API calls remained strictly blocked by default. No unauthorized live API calls were executed. No API keys were exposed in git history, logs, or commit messages.
5. **Stand-in Simulator Provenance:** All benchmark data is explicitly labeled as generated by the calibrated offline stand-in simulator (`is_simulated=True`), with zero simulated data falsely claimed as live Groq inference.

---

## 7. Remaining Limitations

1. **Exact Two-Page Render Check:** While `docs/SUBMISSION_REPORT.md` has been structured compactly into 12 dense sections to fit the 2-page constraint, exact printed page count depends on the target PDF/Word conversion engine's font and margin settings.
2. **Real Groq Benchmark Baseline:** Due to unverified key authorization, Table 2a/2b and Table 3 report calibrated stand-in simulation data rather than live GroqCloud inference.
3. **In-Memory Concurrency Queue:** The admission queue is managed in-process via thread-safe Python locks; a multi-process or distributed deployment would require Redis or RabbitMQ for cross-instance queue coordination.

---

## 8. Reproducibility Instructions

### Offline Testing & Validation:
```bash
# 1. Run all unit and integration tests
pytest -v

# 2. Interactive answerable query with streaming
python scripts/ask.py --source stand-in --stream "What is the formula for Scaled Dot-Product Attention in Attention Is All You Need?"

# 3. Interactive negative-control refusal query
python scripts/ask.py --source stand-in "What specific 16,000 H100 GPU cluster networking topology was used to train the Llama-3 405B base model?"

# 4. Run full benchmark suite (run-scoped, seed 42)
python scripts/run_benchmarks.py --offline-only --seed 42 --run-id phase9_final_eval

# 5. Compute tables and validate CSV schema
python scripts/compute_tables.py --csv data/runs/phase9_final_eval/results.csv --validate
```
