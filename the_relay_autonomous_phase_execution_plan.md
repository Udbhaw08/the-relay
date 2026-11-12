# THE RELAY — Autonomous, Phase-by-Phase Implementation Plan

**Project:** The Relay — Resilient Research Paper Assistant
**Repository:** `Udbhaw08/the-relay`
**Primary real LLM provider:** GroqCloud API
**Default candidate model:** `openai/gpt-oss-20b`
**Offline simulator:** Stand-in, selectable explicitly for tests only
**Execution mode:** Sequential phases, verify each phase, commit and push each successful phase

---

# MASTER INSTRUCTION — READ THIS BEFORE EXECUTING ANY PHASE

You are the autonomous senior engineer responsible for completing this repository's remaining implementation and validation work. Execute the phases in this document **in order, one phase at a time**. Do not merely summarize this plan or return suggested code. Inspect the repository, implement the current phase, test it, review the diff, write its phase report, commit it, and push it before starting the next phase.

The user does not want to manually provide a new prompt after every phase. Therefore, once a phase passes its acceptance gate and its commit is successfully pushed, inspect the actual resulting code and test output, then adapt the next phase to the repository's current state. Do not blindly apply a later instruction if an earlier phase has already implemented it. Record such items as already satisfied, verify them, and continue without unnecessary rewrites.

## A. Non-negotiable project requirements

1. **GroqCloud is the only real LLM provider.** The Gemini runtime integration has already been migrated away. Do not reintroduce Gemini, xAI Grok, OpenAI, NVIDIA NIM, or another real provider unless the user explicitly changes this requirement.
2. **Stand-in is offline/testing-only.** It may be used only when explicitly selected, for example with `LLM_PROVIDER=standin` or the project's explicit stand-in CLI option. A Groq failure must never silently become a stand-in response.
3. **Free-tier safety is mandatory.** The API key belongs to another person. Never assume that an API key proves Free-plan status. Do not upgrade the organization, enable billing, change a subscription, or make a live API call unless the key owner has explicitly authorized this project and confirmed that the organization is on the Groq Free plan. Do not ask the user to paste the key into chat or source code. Read it only from the local environment/secret store.
4. **No unnecessary live calls.** Use mocked tests and stand-in mode for normal development. A live smoke test is optional and is permitted only after explicit owner authorization and Free-plan confirmation. If those are unavailable, mark live verification as pending and continue all offline work.
5. **Preserve the assignment's fixed paper corpus and benchmark questions.** Do not invent papers, ground-truth facts, citations, metrics, or test results. If a source page/section/chunk cannot be verified, report it as missing rather than making one up.
6. **Do not overstate implementation.** Distinguish implemented, tested, simulated, estimated, unverified, and planned functionality everywhere: UI, logs, README, report, and final response.
7. **Keep existing user work.** Do not use destructive commands such as `git reset --hard`, `git clean`, `git checkout --`, `git restore`, or force-push. Never overwrite or discard uncommitted user work.
8. **No fabricated test claims.** Run commands and report actual exit codes and output. A skipped test is not a passed test. A mocked provider test is not a live provider test.
9. **Maintain interfaces where feasible.** Do not break existing CLI commands, dashboard behavior, API response formats, paper ingestion, or the four-stage pipeline without a documented compatibility reason and regression tests.
10. **Do not commit secrets or local data.** Never stage `.env`, API keys, tokens, local logs containing secrets, caches, virtual environments, downloaded model weights, or personal files.

## B. Required Git workflow — commit and push after EVERY phase

The user explicitly authorizes a Git commit and push after each successfully completed phase. Follow this exact workflow:

1. Inspect `git status --short --branch`, `git branch --show-current`, `git rev-parse HEAD`, `git remote -v`, `git diff`, and `git diff --cached` before making changes.
2. The previously observed baseline commit was `599ac070ed77fc0bdcf60f97c8e61402936b2d26`. Verify the actual current HEAD; do not assume the repository is still at that commit.
3. Prefer a dedicated feature branch named `feat/the-relay-groq-hardening`. If it already exists, inspect it and continue on it. Otherwise create it from the current branch without discarding the working tree. **Do not push directly to `main` by default.** Do not merge the branch unless the user separately requests that.
4. The working tree may contain Phase 0 Groq migration changes and pre-existing user edits. Known pre-existing edits from the earlier baseline included `dashboard/app.py`, `scripts/ask.py`, `scripts/make_svg.py`, `the_relay/traffic/__init__.py`, and `docs/SUBMISSION_REPORT.md`. Re-check the actual diffs; do not rely only on this list.
5. Stage only the current phase's intended files/hunks. Use selective/patch staging when a file contains both pre-existing user edits and new phase changes. Do not run `git add .` or `git add -A` blindly.
6. Before committing, inspect `git diff --cached` in full. Confirm that the staged patch contains no unrelated user work, secrets, `.env`, generated junk, or accidental deletions. Run the secret scan and `git diff --cached --check`.
7. Run the full relevant test suite and the phase-specific acceptance checks before committing.
8. Write `docs/implementation/PHASE_<N>_REPORT.md` with the actual changes, commands, results, limitations, and acceptance checklist. Include the report in that phase's commit. Do not invent the commit SHA inside the commit's own report; print the actual SHA after committing.
9. Use a clear commit message, such as `phase-1: fix benchmark aggregation`. Commit only after the phase passes.
10. Push the feature branch to `origin` after every successful phase commit. Verify the push succeeded and record the remote branch and commit SHA. Never use `--force` or `--force-with-lease`.
11. If GitHub authentication, remote access, branch protection, or network failure prevents a push, keep the local commit, report the exact blocker, and **stop before starting the next phase**. Do not claim the phase was pushed. Do not bypass branch protection.
12. If a phase fails its acceptance criteria, fix and retest within that phase. Do not commit an incomplete phase as complete. If it cannot be fixed safely, write a blocker report and stop.
13. At the end, provide all phase commit SHAs, push confirmations, branch name, and final repository status. Do not claim a clean working tree if user changes remain uncommitted.

### Initial dirty-tree handling

Before Phase 0 work, establish a safe baseline snapshot. Do not force a clean tree. If the current working tree already includes the reported Groq migration and Prompt 0.1 changes, audit and close only the remaining issues; do not repeat the migration. Preserve protected pre-existing user edits. If you cannot safely distinguish phase changes from pre-existing changes in a shared file, do not stage that file wholesale. Use selective staging; if safe separation is impossible, stop and explain the exact conflict rather than committing unrelated work.

## C. Per-phase execution protocol

For each phase N:

1. Read the complete phase instructions below.
2. Inspect the actual current code and determine which requirements are already satisfied.
3. Write a short internal implementation checklist based on the actual repository; do not ask the user to approve routine code changes.
4. Implement only the phase's scope. Keep changes small and explainable.
5. Add or update automated tests before claiming completion.
6. Run phase-specific tests, then the full regression suite (`pytest -v`, or the repository's documented equivalent).
7. Run relevant CLI checks, `python scripts/compute_tables.py` where applicable, `git diff --check`, and secret scans.
8. Review the full diff for unrelated changes, compatibility regressions, hardcoded/fabricated metrics, and inaccurate documentation.
9. Write the phase report under `docs/implementation/`.
10. Commit and push the verified phase using Section B.
11. Only after successful push, inspect the resulting implementation and continue to the next phase. Adapt later phases to the actual code; never repeat completed work unnecessarily.

For non-live work, do not stop just because the owner's Groq Free-plan confirmation is unavailable. Continue using mocks and explicit stand-in mode. Keep only the live smoke test and account-specific verification marked pending.

---

# PHASE 0 — BASELINE, GROQ MIGRATION CLOSURE, AND SAFE CHECKPOINT

**Goal:** Verify the already-implemented Gemini-to-Groq migration, close the known documentation/configuration issues, establish the Git feature branch, and create the first verified checkpoint. Do not redo the migration if it is already correct.

## Inspect

- `the_relay/config.py`
- `the_relay/models/groq_client.py`
- `the_relay/models/router.py`
- `the_relay/models/base.py`
- `the_relay/models/stand_in.py`
- `the_relay/models/gemini_client.py` (verify whether absent/deleted)
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `scripts/smoke_test_groq.py`
- `dashboard/app.py`
- `scripts/ask.py`
- `scripts/make_svg.py`
- `README.md`
- `docs/SUBMISSION_REPORT.md`
- `scripts/compute_tables.py`
- all tests

## Requirements

1. Verify Groq is the only real provider in the router. No Gemini/NVIDIA/OpenAI/xAI fallback may remain in the runtime path.
2. Verify the stand-in can be selected explicitly and is never used automatically after a Groq error.
3. Verify the default model is `openai/gpt-oss-20b` only if it remains listed as an active supported model in current official Groq docs. If the current docs change, use the current supported model only after checking Free-plan eligibility; do not silently switch models.
4. Verify `GROQ_API_KEY` is loaded from environment/secret storage. Never print, echo, or include its value in logs, test output, reports, or Git diffs.
5. Verify the Groq SDK dependency is reproducibly pinned/locked. Preserve the tested version if valid; do not upgrade without a reason and tests.
6. Verify retired model IDs are rejected with a clear safe error. Do not hardcode an ever-growing list without documenting why.
7. Verify missing key, missing/empty model, invalid model, 401, 429, timeout, 5xx, malformed response, and secret-scrubbing behavior through mocks.
8. Check current official Groq documentation for model status, context/output limits, and public rate-limit documentation. Cite source URLs in the report. Distinguish public model/catalogue information from the key owner's account-specific Limits page.
9. The key owner's actual Free-plan status and account limits remain `UNVERIFIED` unless the owner confirms them. Public model tables do not prove a particular API key's tier. Never upgrade the account or enable billing.
10. Live smoke test remains blocked unless the key owner has explicitly authorized this project and confirmed Free-plan status. If not confirmed, do not call the API; continue with mocked tests.
11. Fix misleading dashboard wording. Until an authorized live test succeeds, use wording such as `Groq model configured — live access unverified`, not `Live Model`.
12. Remove inaccurate claims such as `zero risk of truncation`. Explain that context is bounded and prompt + retrieved context + history + output must fit within the model's actual context/output budget.
13. Do not claim hybrid BM25+dense retrieval is already implemented if the current retriever is BM25 with lexical/metadata boosts. Describe the actual current behavior accurately and mark dense/hybrid retrieval as planned until Phase 4 passes.
14. Inspect `scripts/compute_tables.py` changes made during migration. Keep only justified provider documentation changes; do not silently modify benchmark computations in this phase.
15. Investigate any prior `git diff --check` nonzero exit. Show the exact whitespace/error output. Preserve pre-existing whitespace-only user modifications; fix only new issues introduced by this work.
16. Run `pytest -v`, the stand-in CLI query, `python scripts/compute_tables.py`, the smoke-test safety gate without credentials, and secret scans. Do not run a live API call without authorization.
17. Preserve assignment terminology, the fixed three-paper corpus, benchmark question IDs, and original CLI/API contracts.

## Acceptance gate

- Groq-only real-provider route verified by tests.
- Stand-in explicit-only behavior verified.
- Model is current and correctly configured, or clearly blocked pending current official verification.
- No secrets in tracked/staged files.
- Dashboard/docs do not claim unverified live access or dense retrieval.
- Full existing tests pass.
- Phase report written.
- Phase 0 changes selectively committed and pushed.

---

# PHASE 1 — CSV SCHEMA, AGGREGATION, AND REPORT CALCULATION CORRECTNESS

**Goal:** Make all benchmark tables mathematically correct and ensure that every metric uses the correct records and denominator.

## Inspect

- `scripts/compute_tables.py`
- `results.csv`
- `the_relay/traffic/logger.py`
- benchmark question definitions
- all benchmark scripts and tests
- `docs/SUBMISSION_REPORT.md`

## Critical known issue

The earlier audit found that retrieval evaluation grouping in `compute_tables.py` used an `OR` condition combining rows whose effective retrieval setting matched a setting with rows whose scenario matched an evaluation scenario. This caused unrelated load-test rows to be included. Correct this based on scenario and run identity, not on effective setting alone.

## Requirements

1. Define/document the CSV schema. Validate required columns, types, statuses, scenario names, retrieval settings, nullable measurements, and numeric ranges.
2. Add a `run_id` (and preserve request ID) so records from separate executions cannot be mixed. Do not assume all historical rows belong to one run.
3. For `eval_setting_a`, `eval_setting_b`, and `eval_setting_c`, include only the corresponding evaluation scenario and intended run. Do not use an `OR` filter that pulls in load-test rows.
4. Validate that each setting uses the same benchmark question IDs and expected question order. Detect missing, duplicated, and unexpected question IDs.
5. Keep requested and effective retrieval settings distinct. A downgraded request must not be counted as if it actually used the requested setting.
6. Use correct denominators. Keep successful answers, incorrect answers, refusals, rate limits, and errors separate. Failed requests must not silently count as wrong factual answers or successful answers.
7. Keep input tokens, output tokens, total tokens, estimated tokens, and provider-reported tokens distinct. Never label output-token averages as total tokens.
8. Failed/no-token requests must have null TTFT, not a fabricated numeric placeholder. Phase 5 will refine timing, but Phase 1 must prevent obviously invalid values entering summary tables.
9. Empty groups must show `N/A` with sample count, not crash or produce zero that looks like a measured value.
10. Detect duplicate request IDs within a run. Do not reject legitimate repeated question IDs across distinct runs.
11. Generate report tables programmatically; do not hardcode totals or percentages.
12. Keep historical result data safe. Do not truncate or overwrite `results.csv` silently. Use run-scoped outputs or explicit append/overwrite controls.
13. Add tests using the existing CSV as a historical fixture. The earlier audit observed 125 historical rows (80 load-test + 45 retrieval evaluation); this is only a fixture expectation, never a production hardcode.

## Tests

- A/B/C groups contain only their own evaluation records.
- A/B/C groups have unique, expected question IDs.
- No accidental cross-scenario mixing.
- Failed requests are excluded from answer-accuracy denominators.
- Correct refusals are separate from correct answers.
- Token columns and averages are labelled correctly.
- Duplicate request IDs are detected within a run.
- Missing columns/invalid values produce clear errors.
- Empty groups yield `N/A`.
- Re-running table generation does not mutate or duplicate source data.

## Acceptance gate

All summary tables are reproducible from validated CSV data; Table 3 or its replacement has correct scenario-only grouping; all tests pass; phase report committed and pushed.

---

# PHASE 2 — INDEPENDENT A/B/C EXPERIMENTS AND REPRODUCIBILITY

**Goal:** Ensure retrieval-setting comparisons are fair, independent, and repeatable.

## Inspect

- `scripts/run_benchmarks.py`
- `the_relay/pipeline/orchestrator.py`
- `the_relay/models/stand_in.py`
- `the_relay/models/router.py`
- `the_relay/traffic/generator.py`
- `the_relay/traffic/logger.py`
- benchmark question definitions

## Requirements

1. Give each evaluation setting an independent experiment context: quota counters, retry state, adaptive degradation state, request counters, and benchmark logger context.
2. Reset or isolate simulator quota state between A/B/C quality evaluations. Do not allow A to exhaust a shared limiter before B or C.
3. Keep quota/load testing separate from retrieval quality experiments. A/B/C retrieval quality should not be affected by unrelated RPM/TPM/RPD exhaustion.
4. Run the same question IDs, order, ground truths, corpus version, and scoring rules for A/B/C.
5. Log both `requested_retrieval_setting` and `effective_retrieval_setting`, plus fallback/degradation reason and timestamp.
6. Do not silently relabel degraded execution. A result executed under A after requesting B must remain visible as requested B/effective A.
7. Record `run_id`, Git commit SHA, timestamps, random seed, provider/model, requested/effective retrieval settings, chunking config, top-K, and a safe configuration snapshot.
8. Fix random seeds for deterministic simulator components. Keep nondeterministic/live runs clearly identified.
9. Preserve failures and refusals in the dataset; never drop bad outcomes to inflate accuracy.
10. Prevent append-only reruns from accidentally mixing old and new results. Use unique run directories or run IDs and explicit aggregation selection.

## Tests

- A/B/C use identical benchmark IDs and order.
- Each starts with independent limiter/retry/degradation state.
- Previous setting cannot contaminate the next.
- Requested/effective modes are accurate.
- Degradation reason is recorded.
- Fixed seeds reproduce deterministic simulator behavior.
- Repeated runs have distinct run IDs.
- Failures remain visible.

## Acceptance gate

A/B/C comparisons are isolated and reproducible; no shared quota contamination; regression tests pass; phase report committed and pushed.

---

# PHASE 3 — FACTUAL ANSWER EVALUATION AND EVIDENCE-BASED CITATION VERIFICATION

**Goal:** Stop marking answers correct merely because they are non-refusals with citations. Evaluate facts against the research-paper evidence.

## Inspect

- `the_relay/pipeline/orchestrator.py`
- `the_relay/retrieval/engine.py`
- citation verification functions
- benchmark question definitions, especially `ground_truth_key_facts`
- chunk metadata and paper ingestion
- tests

## Requirements

1. Inspect current grading. The prior audit found logic equivalent to `not refusal and len(citations) > 0`; this is not factual correctness. Replace it with evidence-grounded grading.
2. Use only existing supported ground-truth facts. If a question lacks defensible annotations, add them only after verifying the paper text/page/section. Otherwise mark it as not yet scorable.
3. Use explicit grades: `correct`, `partially_correct`, `incorrect`, `refused_correctly`, `refused_incorrectly`, and `error`.
4. For answerable questions, measure required-fact coverage and penalize unsupported or contradicted claims. Keep the rubric deterministic where possible.
5. Separate answer accuracy, partial correctness, refusal accuracy, citation validity, evidence coverage, unsupported-claim rate, and execution errors. State each denominator.
6. A citation must resolve to a real document and valid chunk/page/section in the indexed corpus. Reject invented paper titles, invalid chunk IDs, and unsupported page references.
7. Verify the cited passage actually supports the associated claim. Merely mentioning a known paper title is not sufficient.
8. Preserve citation provenance from retrieved chunks through context construction and final answer generation. If the current response format cannot express chunk-level provenance, add a backwards-compatible internal representation and retain the user-facing response contract.
9. Correctly refuse questions unsupported by the fixed paper corpus. A refusal is not a factual answer; report correct refusals separately.
10. If LLM-as-a-judge is added, treat it as a separate secondary measurement. Do not allow it to silently replace deterministic ground-truth scoring.
11. Explicitly test the earlier problematic examples: the WMT BLEU question and the Moshi model-size/training-data question. A generic response with a citation must fail factual grading.

## Tests

- Factually correct answer + valid supporting citation passes.
- Incorrect answer + citation fails.
- Generic answer + citation fails.
- Correct fact with unrelated paper citation fails evidence verification.
- Non-existent chunk/page fails.
- Correct refusal for unanswerable question passes refusal grading.
- Unsupported confident answer fails.
- Missing ground truth is `unscorable`, not automatically correct.
- Factual metrics exclude errors and separately report denominator counts.

## Acceptance gate

Citation presence alone can never award factual correctness; evidence resolution and claim support are tested; all metrics have clear denominators; tests pass; phase report committed and pushed.

---

# PHASE 4 — TRUE HYBRID RETRIEVAL: BM25 + DENSE EMBEDDINGS + RANK FUSION

**Goal:** Implement real dense semantic retrieval and combine it with BM25 using a defensible fusion method. Until this phase passes, describe the current retriever honestly as BM25 with lexical/metadata boosts.

## Inspect

- `the_relay/retrieval/engine.py`
- document ingestion/chunking code
- chunk metadata schemas
- `requirements.txt`
- `the_relay/config.py`
- existing Settings A/B/C definitions
- benchmark ground truths and tests

## Requirements

1. Preserve the current BM25 implementation as a separately testable retrieval mode.
2. Implement actual embedding-based dense retrieval. Prefer the existing `sentence-transformers` dependency if compatible; verify exact installed/version constraints rather than assuming it is already used.
3. Use the same embedding model/version for query and document vectors. Normalize consistently and use cosine similarity or another explicitly documented metric.
4. Cache document embeddings keyed by document/chunk content hash and embedding model/version. Invalidate cache when content/model changes.
5. Support CPU/offline operation where feasible. Do not require an internet download in ordinary unit tests. Make the embedding model configurable and document initial model download requirements.
6. Add explicit retrieval modes: `bm25_only`, `dense_only`, and `hybrid`. Log requested and effective mode. If dense embeddings are unavailable, fail clearly or explicitly downgrade and log the actual mode; never label BM25-only as hybrid.
7. Combine ranks using Reciprocal Rank Fusion (RRF) or another justified, documented fusion strategy. Do not add raw BM25 scores directly to cosine similarity scores without normalization/calibration.
8. Keep metadata boosts (paper hint, section/title) as explicit, separately configurable signals. Ensure they do not hide the raw BM25/dense rankings.
9. Retain the three original papers and the existing benchmark question set. Verify document IDs and page/section/chunk provenance survive indexing and retrieval.
10. Define Settings A/B/C accurately. Each setting must have explicit parameter values and a stored config snapshot. Do not invent which setting is best.
11. Compute retrieval metrics against verified evidence annotations: Recall@K, Precision@K, MRR, and nDCG@K. State definitions and denominators.
12. Keep retrieval-only tests offline with mocked embeddings or deterministic fake vectors. Add optional real embedding integration tests that are skipped unless explicitly requested.
13. Add a retrieval diagnostics mode that shows BM25 ranking, dense ranking, fused ranking, and supporting chunk metadata for a query without exposing secrets.

## Tests

- BM25 retrieves expected chunks.
- Dense retrieval uses actual vector similarity (not lexical boosts).
- Hybrid mode fuses rankings correctly.
- RRF is deterministic for fixed rankings.
- Embedding cache keys include model/version/content.
- Changed content invalidates cached vectors.
- Missing dense model cannot be silently presented as hybrid.
- Metadata/page provenance survives retrieval.
- Recall@K, Precision@K, MRR, and nDCG calculations are correct.
- All three papers can be indexed using the supported ingestion path.

## Acceptance gate

Real dense embedding computation and rank fusion execute; modes and parameters are logged; offline tests pass; report/UI accurately reflects what was actually run; phase report committed and pushed.

---

# PHASE 5 — ACCURATE LATENCY, TTFT, TOKEN, QUEUE, AND COST TELEMETRY

**Goal:** Replace synthetic or inferred performance numbers with accurately labelled measurements.

## Inspect

- `the_relay/traffic/logger.py`
- `the_relay/pipeline/orchestrator.py`
- `the_relay/models/groq_client.py`
- `the_relay/models/stand_in.py`
- `the_relay/traffic/generator.py`
- `scripts/compute_tables.py`

## Requirements

1. Use `time.perf_counter()` or another monotonic clock for elapsed durations.
2. Define timestamps for request start, queue entry, processing start, retrieval start/end, generation start, first non-empty generated text chunk, verification start/end, and completion.
3. True TTFT is measured from a clearly documented start event to the first actual non-empty model text chunk. If no text chunk was generated, TTFT is `null`, never 0 or a fabricated 10 ms.
4. Measure end-to-end wall-clock latency and component durations separately. Do not create component durations by subtraction if boundaries are ambiguous.
5. Integrate streaming through the actual orchestrator path in Phase 7 if not already done. A method existing on the client does not prove the pipeline streams.
6. Store actual provider token usage separately from estimates: `actual_input_tokens`, `actual_output_tokens`, `actual_total_tokens`, and `estimated_*`. Use provider usage metadata when available. If unavailable, actual fields remain null.
7. Distinguish stand-in simulated service delay from actual measured wall-clock elapsed time. Never label simulator values as live Groq latency.
8. Measure queue depth, in-flight count, peak queue depth, queue wait time, and maximum observed concurrency independently. Do not call in-flight count queue depth. Do not use formulas such as `requests // 3` as measured queue values.
9. Remove hardcoded `$0.00` claims. Calculate cost only when actual usage and verified current pricing are available; otherwise show `N/A` or `unknown`. Free-plan use does not mean usage is universally unlimited or that every request has zero economic cost.
10. Percentiles: calculate successful TTFT and successful total latency only from valid successful samples. Report rejected/failed request latency separately. Include sample counts. For zero samples, show `N/A`. Flag very small samples as descriptive, not statistically robust.
11. Ensure failure records have correct nullability/status and do not leak into successful response percentiles.
12. Update CSV schema and documentation compatibly; preserve historical rows and distinguish legacy estimated metrics.

## Tests

- Failure has null TTFT.
- No first text chunk means TTFT is unavailable.
- End-to-end wall time uses monotonic measurements.
- Queue depth differs from in-flight count.
- Actual and estimated tokens are never mixed.
- Missing provider usage remains null.
- Cost is never hardcoded to zero.
- Percentile calculations handle failed, empty, and small samples.
- Simulator latency is distinguishable from live-provider latency.

## Acceptance gate

All displayed latency/token/queue/cost metrics are measured or explicitly labelled estimated/unknown; percentiles use correct records; tests pass; phase report committed and pushed.

---

# PHASE 6 — GROQ-SPECIFIC RATE LIMITING, QUOTAS, BACKOFF, AND RESILIENCE

**Goal:** Correctly handle Groq rate-limit responses and enforce configurable local controls without pretending that public limits equal the key owner's account limits.

## Inspect

- `the_relay/pipeline/resilience.py`
- `the_relay/models/groq_client.py`
- `the_relay/models/stand_in.py`
- `the_relay/models/router.py`
- `the_relay/config.py`
- traffic generator/logger
- related tests

## Requirements

1. Consult current official Groq documentation for rate-limit semantics and headers at implementation time. Record source URL and date checked in the phase report.
2. Distinguish RPM, RPD, TPM, TPD, and (if applicable to the organization) separate ITPM/OTPM. Do not assume a single TPM model if the account console exposes split limits.
3. Rate limits apply at the Groq organization level. Document that other applications/users sharing the same organization/key quota can affect remaining quota.
4. Use configurable local safety caps. Never assume public base limits are the exact limits for this key. Account-specific values must be entered only after owner checks the Groq Console Limits page.
5. Parse actual response headers, including `Retry-After` and relevant `x-ratelimit-*` headers. Validate the exact documented meaning of each header; do not assume a header means RPM if Groq documents it as RPD.
6. Treat `429` as a rate-limit response; preserve status, request ID, retry delay, and safe metadata. Never log API key or authorization headers.
7. Enforce local request/token budgets with a correct rolling window or another clearly defined algorithm. If tokens are estimated before a request, reconcile with actual provider usage after it completes.
8. For daily budgets, use a configurable provider/account reset interpretation. Do not hardcode UTC midnight or a guessed reset time when provider headers/account data are available.
9. Retry only eligible transient errors: documented rate limits, timeouts, transient network failures, and eligible 5xx. Do not retry permanent authentication/invalid-request errors indefinitely. Do not retry a daily-budget exhaustion repeatedly.
10. Implement capped exponential backoff with true full jitter if described as full jitter: `uniform(0, min(max_backoff, base_delay * 2**attempt))`. Respect provider `Retry-After` when supplied, subject to a documented safety cap/policy.
11. Use injectable clock, sleeper, and random source for deterministic tests. Avoid real waiting in unit tests.
12. Bound concurrency and pending work. Measure queue behavior using Phase 5 telemetry; apply backpressure rather than unlimited accumulation.
13. Stand-in supports deterministic injection of RPM/TPM/RPD/TPD exhaustion, 429, timeout, network failure, and 5xx. Keep simulator outcomes clearly labelled simulated.
14. If adaptive degradation changes retrieval mode or top-K, log requested/effective values and reason.

## Tests

- RPM and rolling-window expiry.
- TPM/token reservation and reconciliation.
- Daily budget exhaustion and reset handling.
- Header parsing and `Retry-After` behavior.
- Correct retry for eligible 429/timeout/5xx.
- No retry for auth/permanent 4xx/daily exhaustion.
- Full-jitter backoff bounds and cap.
- Deterministic injected clock/sleeper/randomness.
- Bounded concurrency and backpressure.
- Degradation metadata is accurate.

## Acceptance gate

Groq-specific errors/headers are handled correctly; local quotas are configurable and do not falsely claim account limits; tests pass; phase report committed and pushed.

---

# PHASE 7 — GROQ ADAPTER AND END-TO-END STREAMING INTEGRATION

**Goal:** Ensure the production Groq adapter is truly used by the whole application, not just isolated unit tests, and make streaming/usage/error handling end-to-end.

## Inspect

- `the_relay/models/groq_client.py`
- `the_relay/models/base.py`
- `the_relay/models/router.py`
- `the_relay/pipeline/orchestrator.py`
- `scripts/ask.py`
- `dashboard/app.py`
- requirements and tests

## Requirements

1. Preserve Groq as the sole real provider and the stand-in as explicit offline test mode.
2. Ensure one consistent adapter interface for non-streaming generation, streaming generation, usage metadata, request IDs, rate-limit metadata, and structured errors.
3. Verify the current official Groq SDK/API behavior for streaming and usage inclusion. Do not assume request parameter names without checking the installed pinned SDK and current documentation.
4. Connect `stream_generate()` to the actual orchestrator/application response path where the UI/CLI supports streaming. If a consumer cannot stream, document that limitation; do not claim end-to-end streaming just because the adapter yields chunks.
5. Measure first-token timing at the point the first non-empty text chunk reaches the application layer. Keep provider TTFT and user-visible TTFT distinct if queue/retrieval time is included in the latter.
6. Capture actual usage metadata when returned and propagate it to logger/CSV. Preserve null when absent.
7. Normalize Groq errors into safe structured error types while preserving status, retry information, request ID, and retryability.
8. Ensure no fallback to another provider or stand-in after Groq errors. Missing credentials must result in a clear safe failure in Groq mode.
9. Ensure model name is configurable but validated. No silent model substitution; no retired default model.
10. Keep API keys out of exceptions, logs, UI, transcripts, reports, and CSV.
11. Keep `.env.example` placeholders only and `.gitignore` protection. Do not expose or read a real key into tests.
12. Add mocked adapter tests for stream chunks, usage footer/chunk handling, error mappings, rate-limit headers, malformed responses, and request IDs.
13. Add opt-in live integration test only. It must require explicit owner authorization and Free-plan confirmation, make a single minimal request, and never run as part of ordinary `pytest`.
14. Do not add Groq model calls to every benchmark unless explicitly running the small, authorized live benchmark. Normal CI/benchmark tests must use mocks or stand-in.

## Tests

- Adapter non-stream success.
- Adapter stream success and first chunk timing.
- Orchestrator actually consumes stream path.
- Usage metadata reaches the result logger.
- Rate limit/error metadata reaches resilience layer.
- No silent provider/stand-in fallback.
- Missing key fails safely.
- UI label matches actual provider verification state.
- Standard test suite requires no API key/network.

## Acceptance gate

Groq adapter is integrated end-to-end; streaming claims match actual behavior; usage/errors propagate; no silent fallback; tests pass; phase report committed and pushed.

---

# PHASE 8 — LOAD GENERATOR, SCENARIOS, AND REPRODUCIBLE BENCHMARK EXECUTION

**Goal:** Make the required load scenarios reflect their intended offered traffic and produce run-scoped reproducible data.

## Inspect

- `the_relay/traffic/generator.py`
- `the_relay/traffic/logger.py`
- `the_relay/models/stand_in.py`
- `the_relay/pipeline/resilience.py`
- `scripts/run_benchmarks.py`
- `scripts/compute_tables.py`

## Requirements

1. Inspect the assignment's five required load scenarios and preserve their intended definitions. Do not silently replace the assignment's scenarios with different ones.
2. Steady traffic must be scheduled using start-to-start target intervals or a documented rate scheduler. Do not sleep after request completion in a way that changes the intended interarrival interval.
3. Burst scenario must record offered, submitted, accepted, rejected, successful, and failed counts.
4. Sustained overload must measure actual concurrency, queue depth, backpressure, throughput, and rejection/failure outcomes.
5. Rate-limit scenario must test the configured local/request limit and clearly record the limit values and whether they are simulated or account-confirmed.
6. Daily-budget-exhaustion scenario must stop/deny requests according to policy without pointless retry loops. Its reset behavior must be tested with an injected clock.
7. Keep load testing and retrieval-quality testing isolated as defined in Phase 2.
8. Record run ID, commit SHA, model/provider, retrieval mode/settings, scenario, offered arrival schedule, random seed, config snapshot, and start/end timestamps.
9. Use deterministic seeds for stand-in fault injection and latency assumptions. Label simulator latency as simulated; do not claim it is calibrated from real Groq latency unless a sufficiently sized, authorized real dataset supports that claim.
10. Correctly report offered load, actual arrival rate, successful throughput, failure rate, rate-limit rate, timeout rate, measured concurrency, queue depth, queue wait, successful p50/p95 latency, successful TTFT, and sample counts.
11. Percentiles must use valid successful measurement samples. Failures and rejections are separate. No samples => `N/A`.
12. Preserve historical result runs. Do not silently overwrite or append duplicate rows to a single ambiguous CSV. Make run selection explicit in table generation.
13. Run all offline scenarios first with stand-in. Run live Groq load only if explicitly authorized and Free-plan confirmed, and keep it within a conservative request budget. Do not exhaust the friend's daily quota for testing.

## Tests

- Steady start-to-start intervals.
- Burst dispatch/count accounting.
- Sustained concurrency and bounded queue.
- Configured RPM/TPM/RPD/TPD scenarios.
- Daily budget exhaustion without retry loop.
- Scenario isolation.
- Deterministic seed repeatability.
- Run ID and config metadata correctness.
- No accidental mixing/overwriting of historical runs.

## Acceptance gate

All required scenarios run offline and produce validated run-scoped CSV; measured versus simulated values are explicit; tests pass; phase report committed and pushed.

---

# PHASE 9 — FINAL END-TO-END VALIDATION, SUBMISSION REPORT, AND HANDOFF

**Goal:** Validate the complete pipeline after all implementation phases and produce accurate, reproducible submission artifacts.

## Complete pipeline to validate

1. Paper ingestion for all three assigned papers.
2. Chunking and metadata preservation.
3. BM25 retrieval.
4. Dense retrieval.
5. Hybrid rank fusion.
6. Context assembly.
7. Groq generation in explicitly authorized live mode, or mocked/stand-in mode for offline validation.
8. Streaming if supported end-to-end.
9. Citation resolution and evidence verification.
10. Factual answer grading/refusal classification.
11. Accurate telemetry and request logging.
12. CSV validation and table generation.
13. Load scenarios and retrieval A/B/C evaluations.

## Requirements

1. Run the full unit and offline integration test suite. Report actual passed, failed, skipped, and blocked counts.
2. Run stand-in end-to-end pipeline for a representative answerable question and an unanswerable question. Verify answer and refusal paths separately.
3. Verify Groq provider with mocks. Run a real live smoke test only if the key owner has explicitly authorized usage and confirmed Free-plan status. If not, clearly mark live provider verification as pending; do not imply it passed.
4. Verify all three papers are indexed and their document/page/section/chunk metadata is preserved. Do not fabricate missing paper content.
5. Run the same benchmark questions against A/B/C with independent contexts, effective-setting tracking, and evidence-based grading.
6. Run the five required load scenarios in stand-in mode. Do not run a heavy live benchmark against the friend's quota.
7. Validate the final CSV schema, run IDs, duplicates, missing fields, requested/effective modes, statuses, token provenance, and nullability.
8. Generate all report tables from the selected run data. Every metric must state its denominator/sample count and whether it is actual, simulated, or estimated.
9. Update `docs/SUBMISSION_REPORT.md` to fit the assignment's maximum two-page requirement. Check rendered page count with an appropriate Markdown-to-PDF/Word workflow if available. If exact rendering cannot be verified, say so; do not claim it is within two pages based on word count alone.
10. Remove unsupported claims: no fake hybrid retrieval, no factual accuracy inferred from citation presence, no untested fallback, no unverified live streaming, no assumed real token counts, no inferred queue metrics, no hardcoded zero costs, no account-specific Free quota claims without account evidence.
11. Ensure any required transcript exists at the documented location and contains relevant request/response/evaluation events. Do not point to a missing or untracked file. Redact secrets and personal data.
12. Update README with exact setup, `.env.example`, offline test commands, authorized optional live smoke test instructions, model config, and known limitations.
13. Create `docs/implementation/FINAL_REPORT.md` containing: architecture summary, phases completed, test summary, benchmark run IDs, artifact paths, limitations, Free-tier verification status, live smoke test status, and reproducibility commands.
14. Include previous phase commit SHAs and remote push status in the final handoff. The Phase 9 commit SHA itself must be reported in the terminal/final agent response after commit and push.
15. Do not change the assignment scope or paper corpus.

## Final test commands (adapt only if project tooling requires it)

- `pytest -v`
- `python scripts/ask.py --source stand-in "What is the formula for Scaled Dot-Product Attention in Attention Is All You Need?"`
- `python scripts/compute_tables.py` with an explicit run selection if implemented
- offline benchmark command from README
- `git diff --check`
- secret scan over tracked and staged files

## Acceptance gate

The whole pipeline is tested; report and CSV are regenerated from actual validated run data; known limitations are transparent; final report is saved; Phase 9 commit is pushed.

---

# FINAL HANDOFF FORMAT — RETURN THIS AFTER PHASE 9

Return a concise but complete final handoff containing:

1. **Overall status:** completed / partially completed / blocked.
2. **Groq status:** configured model, whether key-owner authorization was received, whether Free plan was confirmed, whether live smoke succeeded, and exact reason if not tested. Never reveal the key.
3. **Phase-by-phase table:** phase number, summary, test result, commit SHA, push status, and report path.
4. **Tests:** exact commands, passed/failed/skipped/blocked counts, and any failure details.
5. **Benchmarks:** run IDs, selected configuration, real-versus-simulated provenance, CSV path, and report path.
6. **GitHub:** remote branch, all commit SHAs, latest pushed SHA, and any push limitations. Confirm that no force-push or direct main push occurred.
7. **Artifacts:** paths to final CSV, submission report, implementation reports, transcript if required, and reproducibility instructions.
8. **Remaining limitations:** explicit list; do not hide anything that was not verified.
9. **Final repository state:** output of `git status --short --branch`. State whether any user changes remain uncommitted.

Do not say “all complete” if any critical acceptance gate failed. Do not invent results or claim a push that did not succeed.

---

# START EXECUTION NOW

Begin with the Master Instruction and Phase 0. Execute phases sequentially through Phase 9. Do not stop after merely reading this file. Do not ask the user to paste each phase again. Only stop when a defined safety/authorization requirement, an unfixable critical test failure, an unsafe Git ambiguity, or a GitHub push blocker prevents a safe continuation. In those cases, report the exact blocker and preserve all work.
