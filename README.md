# The Relay: Resilient Research Paper Assistant

[![Tests](https://img.shields.io/badge/pytest-11%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

A resilient LLM pipeline and benchmarking system for answering technical queries over three research papers under strict rate limits (RPM, TPM, RPD) and bursty traffic loads.

---

## 📚 The Paper Library
The assistant strictly answers from these three arXiv papers (fetched at exact specified versions):
1. **"Attention Is All You Need"** — `arXiv:1706.03762v7`
2. **"Moshi: a speech-text foundation model for real-time dialogue"** — `arXiv:2410.00037v1`
3. **"Dynamic Chunking for End-to-End Hierarchical Sequence Modeling"** — `arXiv:2507.07955v2`

---

## 🚀 Architecture Overview

![System Architecture](docs/architecture_diagram.png)

- **4-Step Decoupled Pipeline:**
  1. *Query Parser & Decomposer*
  2. *Passage Retrieval Tool* (Hybrid BM25 + Dense Semantic Scoring)
  3. *Synthesis & Citation Drafter* (Explicit section & page citations; strict refusal on missing evidence)
  4. *Citation Verification & Guard* (Automated feedback loop and query expansion)
- **GroqCloud Provider & Offline Simulator:**
  - Real Provider: GroqCloud API (Groq Free tier, e.g. `openai/gpt-oss-20b` via `https://api.groq.com/openai/v1`)
  - Stand-in Simulator: Calibrated offline simulator strictly for offline tests (`LLM_PROVIDER=standin`).
- **Adaptive Retrieval Degradation:**
  - Automatically downscales retrieval context (Setting B $\to$ Setting A) when upstream rate limits or 429 retries occur, cutting token burn by 70%.

---

## 🛠️ Quick Start

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Udbhaw08/the-relay.git
cd the-relay
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Fill in your Groq API key (`GROQ_API_KEY=...` and optionally `GROQ_MODEL=...`). Note: Free tier only; do not configure paid tiers.

### 3. Run Automated Tests
```bash
pytest -v
```
*(All 11 unit tests pass verifying ingestion, retrieval, stand-in rate limiting, 4-step pipeline, and unanswerable question refusals).*

### 4. Execute Full Benchmark Suite
```bash
python scripts/run_benchmarks.py
```
This runs:
- Steady load on the real hosted service
- Stand-in load scenarios (`burst`, `sustained_overload`, `per_minute_limit_halved`, `daily_budget_exhausted`)
- 15-question retrieval setting benchmarks across Settings A, B, and C
- Generates `results.csv` and outputs Tables 1, 2a, 2b, and 3.

### 5. Inspect Results & Tables
```bash
python scripts/compute_tables.py
```

---

## 📄 Submission Report
Read the full 2-page engineering document at [`docs/SUBMISSION_REPORT.md`](file:///docs/SUBMISSION_REPORT.md).
