# Phase 3 Implementation Report: Factual Answer Evaluation and Evidence-Based Citation Verification

**Date:** 2026-11-12<br>
**Branch:** `feat/the-relay-groq-hardening`<br>
**Phase Status:** COMPLETED<br>
**Test Suite:** 62 passed / 0 failed (15 dedicated Phase 3 tests in `tests/test_factual_evaluation.py`)

---

## 1. Executive Summary & Objective

In Phase 3, we eliminated the superficial grading logic identified during the initial code audit:
```python
# Legacy superficial grading (EXCISED):
grade = "correct" if (not is_refusal and len(citations) > 0) else "wrong"
```
Under that legacy check, any non-refusal answer containing bracketed text (even completely generic or fabricated) was awarded `correct` without validating factual accuracy, paper existence, page bounds, chunk retrieval provenance, or evidence support.

We replaced this with a rigorous, deterministic factual evaluation and citation verification engine in [`the_relay/eval/grader.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/eval/grader.py), backed by:
1. **Corpus Boundaries:** Explicit page counts and aliases for the three mandatory papers:
   - *Attention Is All You Need* (`1706.03762v7`): 15 pages max.
   - *Moshi: a speech-text foundation model for real-time dialogue* (`2410.00037v1`): 66 pages max.
   - *Dynamic Chunking for End-to-End Hierarchical Sequence Modeling* (`2507.07955v2`): 39 pages max.
2. **Evidence-Based Citation Resolution:** Parsing bracketed citations, rejecting invented titles, bounds-checking page numbers, ensuring cited chunks were retrieved in context, and verifying that cited text actually supports the claimed facts.
3. **Deterministic Factual Rubrics:** Formulating exact rubrics for all 15 benchmark questions, penalizing generic canned answers, and requiring explicit values (e.g. 28.4 / 41.8 BLEU scores for Q03, 7B Helena parameter size for Q08).
4. **Explicit Grade Spectrum:** Supporting `correct`, `partially_correct`, `wrong` (and `incorrect`), `refused_correctly`, `refused_wrongly` (and `refused_incorrectly`), `unscorable`, `error`, and `rate_limited`.
5. **Denominator Transparency:** `compute_evaluation_metrics()` separates evaluated answerable questions, unanswerable questions, execution errors, and citation grounding with explicit denominators.

---

## 2. Key Architectural Changes

### 2.1 Evidence-Based Citation Verifier (`CitationVerifier`)
Implemented in [`the_relay/eval/grader.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/eval/grader.py):
- **Syntactic Parsing:** Extracts bracketed citations such as `[Attention Is All You Need, Page 4, Section 3.2.1]`, `[Passage 1]`, and direct chunk IDs (`1706.03762v7_p4_c7`).
- **Corpus Resolution:** Resolves paper names and aliases against `REQUIRED_PAPERS`. Invented or external papers (e.g., Llama-3, GPT-4) fail corpus verification (`resolves_to_corpus = False`).
- **Page Bounds Checking:** Rejects page numbers exceeding physical PDF page counts (e.g., Page 99 on Attention fails: `resolves_to_page_range = False`).
- **Context Provenance & Evidence Support:** Verifies that the cited passage was among the chunks retrieved in Step 2, and that the passage text contains the numbers, entities, and technical concepts asserted in the claim (`supports_evidence = True`). If an answer cites Moshi for an Attention claim, or cites an unretrieved passage, verification fails.

### 2.2 Factual Grader (`FactualGrader`)
Implemented in [`the_relay/eval/grader.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/eval/grader.py):
- **Refusal Classification:**
  - Negative control questions (`q13_llama3_hardware_infra`, `q14_private_dna_cohorts`, `q15_quantum_attention_speedup`): An explicit refusal receives `refused_correctly`. An invented or confident answer receives `refused_wrongly`.
  - Answerable benchmark questions: An explicit refusal receives `refused_wrongly`.
- **Missing Ground Truth (`unscorable`):** Questions without ground-truth annotations are marked `unscorable`, preventing automatic awards of correctness.
- **Critical Fact Gating:** Key facts have critical gating flags (e.g., Q03 requires 28.4 and 41.8; Q08 requires 7B / Helena). Generic fluff that omits the critical values is rejected as `wrong` (coverage = 0%).
- **Grade Assignment Rubric:**
  - `correct`: 100% fact coverage AND all citations valid, grounded in retrieved chunks, and supporting the claims.
  - `partially_correct`: Core facts present with valid grounded citations, but secondary details omitted.
  - `wrong`: Missing critical facts, generic canned response, wrong values, ungrounded citations, or unsupported claims.

### 2.3 Structured Telemetry & Provenance Preservation
- In [`the_relay/pipeline/orchestrator.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/pipeline/orchestrator.py), `PipelineResult` retains `citations_found: list[str]` for backwards compatibility and adds `citation_details: list[dict]` preserving:
  - `paper_id`, `paper_title`, `page_number`, `section`, `chunk_id`, `resolves_to_corpus`, `resolves_to_page_range`, `grounded_in_retrieved`, `supports_evidence`, and `details`.
- In [`the_relay/traffic/schema.py`](file:///c:/Users/udbha/Desktop/aivoice/the_relay/traffic/schema.py), `ALLOWED_ANSWER_GRADES` was expanded to accept `"incorrect"` and `"refused_incorrectly"` alongside legacy synonyms `"wrong"` and `"refused_wrongly"`.

---

## 3. Resolution of Earlier Problematic Examples

| Benchmark Question | Ground-Truth Requirement | Generic Response Outcome | Evidence-Based Response Outcome |
| :--- | :--- | :--- | :--- |
| **Q03: Transformer BLEU Scores** | 28.4 (En-De), 41.8 (En-Fr) on Page 8 | **FAILED (`wrong`)**<br>Generic phrase "achieved state of the art BLEU" lacks 28.4/41.8 numbers. | **PASSED (`correct`)**<br>Includes 28.4 and 41.8 with valid citation to Page 8. |
| **Q08: Moshi Model Size** | 7B parameter foundation model (Helena) | **FAILED (`wrong`)**<br>Generic answer "trained on speech and audio" misses core 7B parameter fact. | **PASSED (`correct`)**<br>Includes 7B parameter Helena model size with valid citation. |
| **Q13: Llama-3 Topology** | Expected Negative (Papers do not say) | **FAILED (`refused_wrongly`)**<br>Hallucinating InfiniBand topology is caught as wrong refusal. | **PASSED (`refused_correctly`)**<br>Refusal correctly identified without hallucination. |
| **Unrelated Paper Citation** | Citation must support claimed facts | **FAILED (`wrong`)**<br>Asserting BLEU scores while citing Moshi fails evidence grounding. | **PASSED (`correct`)**<br>Citation to Attention Page 8 verified against retrieved chunk. |
| **Out-of-Bounds Page** | Page <= 15 for Attention | **FAILED (`wrong`)**<br>Citing Page 99 fails page bounds check. | **PASSED (`correct`)**<br>Citing Page 4 passes page bounds check. |

---

## 4. Verification and Test Results

The dedicated test suite [`tests/test_factual_evaluation.py`](file:///c:/Users/udbha/Desktop/aivoice/tests/test_factual_evaluation.py) was added with 15 tests:
1. `test_factually_correct_answer_with_valid_citation_passes`: PASSED
2. `test_incorrect_facts_with_valid_citation_fails`: PASSED
3. `test_generic_answer_with_citation_fails_q03`: PASSED
4. `test_specific_bleu_scores_pass_q03`: PASSED
5. `test_generic_answer_with_citation_fails_q08`: PASSED
6. `test_specific_moshi_size_passes_q08`: PASSED
7. `test_correct_facts_with_unrelated_paper_citation_fails`: PASSED
8. `test_nonexistent_page_citation_fails`: PASSED
9. `test_unindexed_paper_citation_fails`: PASSED
10. `test_correct_refusal_for_unanswerable_question`: PASSED
11. `test_unsupported_confident_answer_fails_on_negative_control`: PASSED
12. `test_refusal_on_answerable_question_fails`: PASSED
13. `test_missing_ground_truth_is_unscorable`: PASSED
14. `test_evaluation_metrics_denominator_correctness`: PASSED
15. `test_pipeline_citation_provenance_integration`: PASSED

Full repository test suite execution:
- Total tests: **62 passed**
- Execution time: ~60.76s
- Failures: **0**

---

## 5. Acceptance Checklist

- [x] Decommissioned superficial grading (`len(citations) > 0`).
- [x] Evidence resolution verifies paper existence, physical page bounds, and retrieved chunk provenance.
- [x] Claim support verifies that cited passage text contains the asserted facts and numbers.
- [x] Problematic examples (Q03 BLEU scores, Q08 Moshi model size) explicitly tested: generic responses fail.
- [x] Unanswerable questions require explicit refusals; confident hallucinations fail.
- [x] Missing ground-truth questions report `unscorable`.
- [x] Infrastructure execution errors excluded from factual evaluation denominators.
- [x] All 62 unit and integration tests passing.
