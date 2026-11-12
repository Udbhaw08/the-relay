# PHASE 0 IMPLEMENTATION REPORT: Baseline, Groq Migration Closure, and Safe Checkpoint

**Date:** 2026-11-12<br>
**Feature Branch:** `feat/the-relay-groq-hardening`<br>
**Baseline Commit:** `ce580ef8d02839597e1d8bb953e1a715d020af10` (incorporating prior Groq client migration)<br>
**Target Provider:** GroqCloud API (`api.groq.com/openai/v1`)<br>
**Target Model:** `openai/gpt-oss-20b`<br>
**Stand-in Mode:** Offline/test-only, selectable explicitly (`LLM_PROVIDER=standin` or `source="stand-in"`)

---

## 1. Executive Summary

Phase 0 establishes the verified baseline for "The Relay" hardening plan on a dedicated feature branch `feat/the-relay-groq-hardening`. The Gemini-to-Groq migration was verified to be complete and fully functional without remnants of Gemini, NVIDIA NIM, or xAI Grok in the runtime execution paths. All 31 automated tests pass cleanly. Honest documentation wording was enforced across the Streamlit dashboard and README to explicitly state that live Groq access is unverified until key-owner confirmation, and that dense semantic retrieval is planned for Phase 4 (with the current engine operating as BM25 with lexical/metadata boosts).

---

## 2. Requirements Verification

### 2.1 Groq as Sole Real Provider & Router Isolation
- **Inspection:** `the_relay/models/router.py`, `the_relay/config.py`, `the_relay/models/groq_client.py`.
- **Status:** Satisfied.
- **Details:** `gemini_client.py` has been completely deleted from the codebase (`Test-Path` returned `False`). The router routes `groq`, `real`, and `live` exclusively to `GroqClient`. No silent fallbacks to stand-in or any secondary provider exist in `GroqClient` or `ModelRouter`.

### 2.2 Stand-in Simulator Isolation
- **Inspection:** `the_relay/models/stand_in.py`, `the_relay/models/router.py`.
- **Status:** Satisfied.
- **Details:** The stand-in is invoked only when explicitly requested (`LLM_PROVIDER=standin` or `source="stand-in"`). In the event of an upstream Groq failure (401, 429, 5xx, timeout), the pipeline records the failure status or retries with exponential backoff; it never silently substitutes stand-in output.

### 2.3 Production Model Status & Official Documentation
- **Inspection:** Official Groq documentation via web search citations:
  - Models Catalogue: [Groq Supported Models](https://console.groq.com/docs/models)
  - Rate Limits Documentation: [Groq Rate Limits](https://console.groq.com/docs/rate-limits)
  - Account Limits Console: [Groq Limits Console](https://console.groq.com/settings/limits)
- **Status:** Satisfied.
- **Details:** `openai/gpt-oss-20b` is actively listed and supported on Groq. The retired model `llama-3.3-70b-versatile` (decommissioned August 16, 2026) is explicitly blocked in `the_relay/config.py` and `the_relay/models/groq_client.py`.

### 2.4 Free-Tier & Key-Owner Safety
- **Status:** Satisfied (Safety Gate Active).
- **Details:** The API key belongs to an external owner. The organization's Free-tier status and specific rate limits remain `UNVERIFIED` until explicitly confirmed by the key owner. No live API calls were made during verification. `scripts/smoke_test_groq.py` enforces `--confirm-free-tier` and `--authorized` flags; running without them safely aborted with exit code 1.

### 2.5 Secret Scrubbing & Safe Storage
- **Inspection:** `.env` and `.env.local` are tracked in `.gitignore` and ignored by git.
- **Details:** `the_relay/models/groq_client.py` implements `sanitize_error()` which strips `gsk_` tokens, Bearer headers, and Authorization headers. Secret scan across git-tracked files confirmed zero real credentials committed.

### 2.6 Honest Terminology & Accurate Descriptions
- **Dashboard (`dashboard/app.py`):**
  - Updated model selector label from `🟢 Live Model` to `🟢 Groq model configured — live access unverified (openai/gpt-oss-20b)`.
  - Updated Step 2 stepper and architecture summary to state `BM25 + Lexical Boosts (dense planned in Phase 4)`.
  - Updated load test button to clearly state authorization requirement.
- **README (`README.md`):**
  - Updated retrieval description to `BM25 with Lexical & Metadata Boosts; Dense Semantic Scoring planned in Phase 4`.
  - Updated test badge and quick start to report 31 passing unit tests.

---

## 3. Test & Verification Log

| Command | Exit Code | Observed Output / Result |
| :--- | :---: | :--- |
| `pytest -v` | 0 | 31 passed in 45.60s |
| `python scripts/compute_tables.py` | 0 | Tables 1, 2a, 2b, and 3 computed from `results.csv` |
| `python scripts/ask.py --source stand-in "..."` | 0 | Answer generated, 4 steps executed, citation verified |
| `python scripts/smoke_test_groq.py` | 1 | Safety blocked: Key owner authorization required |
| `git diff --check` | 0 | Clean (no whitespace issues or trailing spaces) |
| Secret Scan (`git grep -i "gsk_"`) | 0 | Clean (only test dummy keys and regex patterns in test files) |

---

## 4. Acceptance Gate Evaluation

- [x] Groq-only real-provider route verified by tests.
- [x] Stand-in explicit-only behavior verified.
- [x] Model is current (`openai/gpt-oss-20b`) and verified via official docs.
- [x] No secrets in tracked/staged files.
- [x] Dashboard/docs do not claim unverified live access or dense retrieval.
- [x] Full existing tests pass (31/31).
- [x] Phase report written.

---

## 5. Next Steps

Proceed to Phase 1: CSV Schema, Aggregation, and Report Calculation Correctness (fixing the retrieval evaluation grouping OR filter in `compute_tables.py`, adding `run_id`, validating denominators and schemas).
