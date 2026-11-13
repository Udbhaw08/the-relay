"""
Evidence-Based Citation Verification and Factual Grading Engine for The Relay.
Stops marking answers correct merely because they have citations.
Evaluates claims against retrieved chunk provenance and ground-truth evidence.
"""
import re
from dataclasses import dataclass, field
from typing import Optional, Any
from the_relay.config import REQUIRED_PAPERS
from the_relay.retrieval.chunker import Chunk
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS, BenchmarkQuestion

# Corpus definitions with verified page counts and titles
CORPUS_PAPERS = {
    "1706.03762v7": {
        "title": "Attention Is All You Need",
        "max_pages": 15,
        "aliases": [
            "attention is all you need",
            "attention",
            "vaswani",
            "vaswani et al.",
            "transformer"
        ]
    },
    "2410.00037v1": {
        "title": "Moshi: a speech-text foundation model for real-time dialogue",
        "max_pages": 66,
        "aliases": [
            "moshi",
            "mimi",
            "defossez",
            "defossez et al.",
            "speech-text foundation model"
        ]
    },
    "2507.07955v2": {
        "title": "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        "max_pages": 39,
        "aliases": [
            "dynamic chunking",
            "h-net",
            "dynamic chunking for end-to-end hierarchical sequence modeling",
            "hierarchical sequence modeling"
        ]
    }
}

@dataclass
class ParsedCitation:
    raw: str
    paper_id: Optional[str] = None
    paper_title: Optional[str] = None
    page_number: Optional[int] = None
    section: Optional[str] = None
    chunk_id: Optional[str] = None
    is_valid_format: bool = False
    resolves_to_corpus: bool = False
    resolves_to_page_range: bool = False
    grounded_in_retrieved: bool = False
    supports_evidence: bool = False
    details: str = ""

@dataclass
class GradeResult:
    grade: str  # correct, partially_correct, wrong, refused_correctly, refused_wrongly, error, unscorable, rate_limited
    fact_coverage: float = 0.0
    matched_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    citations_verified: list[ParsedCitation] = field(default_factory=list)
    citation_validity_ratio: float = 0.0
    evidence_grounded_ratio: float = 0.0
    is_refusal: bool = False
    details: str = ""

class CitationVerifier:
    def __init__(self, corpus_meta: Optional[dict[str, dict]] = None):
        self.corpus = corpus_meta or CORPUS_PAPERS

    def extract_citations(self, text: str) -> list[str]:
        """Extract bracketed citations matching [Paper, Page X, Section Y] or [Passage N] or [chunk_id]."""
        # Normalize non-breaking and thin spaces (e.g. \u202f used between Page and number)
        norm_text = re.sub(r"[\u202f\u00a0\u200b]", " ", text)
        # Match bracketed strings that are NOT LaTeX display math \[ ... \]
        matches = re.findall(r"(?<!\\)\[([^\]\n]+)\]", norm_text)
        clean_citations = []
        for m in matches:
            m_strip = m.strip()
            # Ignore markdown image links or LaTeX equations or single footnote digits
            if m_strip and not m_strip.startswith("http") and not m_strip.startswith("\\"):
                clean_citations.append(m_strip)
        return clean_citations

    def _resolve_paper(self, text_hint: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve paper name or alias to canonical (paper_id, canonical_title)."""
        hint_lower = text_hint.lower().strip()
        for pid, meta in self.corpus.items():
            if hint_lower == pid.lower() or meta["title"].lower() in hint_lower or hint_lower in meta["title"].lower():
                return pid, meta["title"]
            for alias in meta["aliases"]:
                if alias in hint_lower or hint_lower in alias:
                    return pid, meta["title"]
        return None, None

    def parse_and_verify_citation(
        self, raw_cit: str, retrieved_chunks: list[Chunk], claim_text: Optional[str] = None
    ) -> ParsedCitation:
        """
        Parse a single citation string, check corpus membership, page bounds,
        and verify resolution against retrieved chunks.
        """
        res = ParsedCitation(raw=raw_cit)
        cit_clean = raw_cit.strip()

        # Case 1: Passage reference (e.g. "Passage 1" or "Reference Passage 2")
        passage_match = re.match(r"(?:Reference\s+)?Passage\s*\[?(\d+)\]?", cit_clean, re.I)
        if passage_match:
            idx = int(passage_match.group(1)) - 1
            if 0 <= idx < len(retrieved_chunks):
                ch = retrieved_chunks[idx]
                res.paper_id = ch.paper_id
                res.paper_title = ch.paper_title
                res.page_number = ch.page_number
                res.section = ch.section
                res.chunk_id = ch.chunk_id
                res.is_valid_format = True
                res.resolves_to_corpus = True
                res.resolves_to_page_range = True
                res.grounded_in_retrieved = True
                res.supports_evidence = True
                res.details = f"Resolved via Passage [{idx+1}] to {ch.chunk_id}"
                return res
            else:
                res.is_valid_format = True
                res.details = f"Passage index {idx+1} out of bounds for {len(retrieved_chunks)} retrieved chunks"
                return res

        # Case 2: Direct Chunk ID reference (e.g. "1706.03762v7_p4_c7")
        chunk_id_match = re.match(r"(\w+\.?\w*)_p(\d+)_c(\d+)", cit_clean)
        if chunk_id_match:
            pid = chunk_id_match.group(1)
            pg = int(chunk_id_match.group(2))
            res.chunk_id = cit_clean
            res.paper_id = pid
            res.page_number = pg
            res.is_valid_format = True
            if pid in self.corpus:
                res.resolves_to_corpus = True
                res.paper_title = self.corpus[pid]["title"]
                res.resolves_to_page_range = (1 <= pg <= self.corpus[pid]["max_pages"])
            matching_ch = [c for c in retrieved_chunks if c.chunk_id == cit_clean]
            if matching_ch:
                res.grounded_in_retrieved = True
                res.supports_evidence = True
                res.details = f"Resolved to retrieved chunk {cit_clean}"
            else:
                res.details = f"Chunk {cit_clean} was not retrieved in context"
            return res

        # Case 3: Standard academic citation: [Paper Title, Page X, Section Y]
        parts = [p.strip() for p in cit_clean.split(",")]
        res.is_valid_format = True

        paper_part = parts[0]
        pid, ptitle = self._resolve_paper(paper_part)
        if not pid:
            res.resolves_to_corpus = False
            res.details = f"Unindexed or invented paper title: '{paper_part}'"
            return res

        res.paper_id = pid
        res.paper_title = ptitle
        res.resolves_to_corpus = True

        # Extract page number
        page_num = None
        section_name = None
        for p in parts[1:]:
            page_m = re.search(r"(?:page|pg\.?|p\.)\s*([0-9]+)", p, re.I)
            if page_m:
                page_num = int(page_m.group(1))
            sec_m = re.search(r"(?:section|sec\.?)\s*([0-9A-Za-z\.\-]+)", p, re.I)
            if sec_m:
                section_name = sec_m.group(1)

        res.page_number = page_num
        res.section = section_name

        max_pg = self.corpus[pid]["max_pages"]
        if page_num is not None:
            if 1 <= page_num <= max_pg:
                res.resolves_to_page_range = True
            else:
                res.resolves_to_page_range = False
                res.details = f"Page {page_num} out of bounds for {ptitle} (max {max_pg} pages)"
                return res
        else:
            # Citation did not specify page number
            res.resolves_to_page_range = False
            res.details = f"Missing page number for citation to '{ptitle}'"
            return res

        # Check resolution to retrieved context chunks
        matching_chunks = [
            c for c in retrieved_chunks
            if c.paper_id == pid and c.page_number == page_num
        ]
        if matching_chunks:
            chunk = matching_chunks[0]
            chunk_text_lower = chunk.text.lower()
            supports = True
            if claim_text:
                clean_claim = re.sub(r"\[[^\]]+\]", "", claim_text)
                claim_nums = re.findall(r"\b\d+(?:\.\d+)?\b", clean_claim)
                significant_nums = [n for n in claim_nums if n not in {"0", "1", "2", "3", "4", "5"}]
                if significant_nums:
                    if not any(num in chunk.text for num in significant_nums):
                        supports = False
                claim_tokens = [
                    w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", clean_claim)
                    if w.lower() not in {"citation", "page", "section", "model", "paper", "based", "that", "this", "from", "with"}
                ]
                if claim_tokens:
                    hits = sum(1 for t in claim_tokens if t in chunk_text_lower)
                    if hits == 0 or (hits / len(claim_tokens) < 0.15):
                        supports = False

            res.chunk_id = chunk.chunk_id
            res.supports_evidence = supports
            if supports:
                res.grounded_in_retrieved = True
                res.details = f"Grounded in retrieved chunk {res.chunk_id} with supporting evidence"
            else:
                res.grounded_in_retrieved = False
                res.details = f"Passage {res.chunk_id} in {ptitle} does not contain evidence supporting the claimed facts"
        else:
            res.grounded_in_retrieved = False
            res.supports_evidence = False
            res.details = f"Passage for {ptitle} Page {page_num} was NOT in retrieved context"

        return res

    def verify_citations(self, draft_text: str, retrieved_chunks: list[Chunk]) -> tuple[bool, list[ParsedCitation], str]:
        """
        Verify all citations extracted from text.
        Returns (all_valid, parsed_citations, summary).
        """
        raw_citations = self.extract_citations(draft_text)
        if not raw_citations:
            return False, [], "No citations found in answer"

        parsed = [
            self.parse_and_verify_citation(r, retrieved_chunks, claim_text=draft_text)
            for r in raw_citations
        ]
        all_valid = all(
            p.resolves_to_corpus and p.resolves_to_page_range and p.grounded_in_retrieved and p.supports_evidence
            for p in parsed
        )
        summary = (
            f"Verified {len(parsed)} citations: "
            f"{sum(1 for p in parsed if p.grounded_in_retrieved and p.supports_evidence)} grounded with supporting evidence."
        )
        return all_valid, parsed, summary

def is_explicit_refusal(text: str) -> bool:
    """Detect if response is an explicit refusal due to lack of corpus evidence."""
    t = text.lower()
    refusal_patterns = [
        "the provided papers do not",
        "the provided research papers do not",
        "papers do not contain",
        "papers do not say",
        "does not contain information",
        "do not contain information",
        "not mentioned in the provided",
        "not mentioned in any of the",
        "cannot answer this question based on",
        "no information is provided",
        "outside the scope of the provided papers",
        "the papers do not state",
        "the provided documents do not",
        "none of the provided papers",
        "does not state the answer"
    ]
    return any(p in t for p in refusal_patterns)

# Precise factual verification rubrics for the 15 benchmark questions
BENCHMARK_FACT_RUBRICS: dict[str, list[dict[str, Any]]] = {
    "q01_attention_formula": [
        {
            "id": "formula",
            "description": "Scaled dot-product attention formula: softmax(QK^T / sqrt(d_k))V",
            "keywords": ["softmax"],
            "any_of": ["qk^t", "qk", "q k", "query and key", "queries and keys"],
            "scaling_term": ["sqrt", "d_k", "dk", "scaling"]
        },
        {
            "id": "scaling_rationale",
            "description": "Scaling factor prevents large dot products from pushing softmax into small gradients",
            "keywords": ["gradient", "gradients"],
            "any_of": ["large dot product", "small gradient", "vanishing", "pushing", "magnitude", "counteract", "steep"]
        }
    ],
    "q02_transformer_dimensions": [
        {
            "id": "d_model",
            "description": "d_model = 512",
            "keywords": ["512"]
        },
        {
            "id": "heads",
            "description": "number of heads h = 8",
            "keywords": ["8"]
        },
        {
            "id": "d_k_d_v",
            "description": "d_k = 64 and d_v = 64",
            "keywords": ["64"]
        }
    ],
    "q03_transformer_bleu": [
        {
            "id": "bleu_en_de",
            "description": "28.4 BLEU on English-to-German",
            "keywords": ["28.4"],
            "critical": True
        },
        {
            "id": "bleu_en_fr",
            "description": "41.8 BLEU on English-to-French",
            "keywords": ["41.8"],
            "critical": True
        }
    ],
    "q04_ffn_layer": [
        {
            "id": "ffn_formula",
            "description": "FFN formula max(0, xW_1 + b_1)W_2 + b_2 or linear/ReLU transformations",
            "keywords": ["max(0", "relu", "w_1", "w1", "feed-forward", "linear", "inner-layer"]
        },
        {
            "id": "d_ff",
            "description": "Inner layer dimensionality d_ff = 2048",
            "keywords": ["2048"]
        }
    ],
    "q05_mimi_codec_framerate": [
        {
            "id": "framerate",
            "description": "12.5 Hz framerate",
            "keywords": ["12.5"]
        },
        {
            "id": "codebooks",
            "description": "8 RVQ codebooks",
            "keywords": ["8 codebook", "8 rvq", "eight codebooks", "8"]
        }
    ],
    "q06_moshi_latency_budget": [
        {
            "id": "latency",
            "description": "160ms theoretical conversational latency",
            "keywords": ["160"]
        },
        {
            "id": "stride",
            "description": "80ms audio frame stride",
            "keywords": ["80"]
        }
    ],
    "q07_moshi_multistream": [
        {
            "id": "multistream",
            "description": "Hierarchical multi-stream architecture with parallel audio and text streams",
            "keywords": ["multi-stream", "multistream", "parallel", "streams", "interleav"]
        },
        {
            "id": "speech_text_alignment",
            "description": "Temporal alignment of user audio, agent audio, and text",
            "keywords": ["audio", "speech"],
            "must_also_have": ["text"]
        }
    ],
    "q08_moshi_pretraining_data": [
        {
            "id": "model_size",
            "description": "7B parameter foundation model (Helena)",
            "keywords": ["7b", "7 billion", "7-billion", "helena"],
            "critical": True
        },
        {
            "id": "pretraining_modalities",
            "description": "Pre-trained on text and audio/speech data",
            "keywords": ["text", "speech", "audio", "pretrain", "pre-train"]
        }
    ],
    "q09_dynamic_chunking_concept": [
        {
            "id": "raw_bytes",
            "description": "Operates directly on raw bytes",
            "keywords": ["byte", "bytes", "raw byte"]
        },
        {
            "id": "replaces_bpe",
            "description": "Eliminates tokenizer heuristic / replaces BPE",
            "keywords": ["bpe", "tokenizer", "tokenization", "byte-pair"]
        },
        {
            "id": "dynamic_boundaries",
            "description": "Learned dynamic segmentation boundaries",
            "keywords": ["dynamic", "segment", "chunk", "boundary", "boundaries"]
        }
    ],
    "q10_hnet_hierarchy_stages": [
        {
            "id": "twice_size",
            "description": "Matches token-based Transformers of twice its size",
            "keywords": ["twice", "2x", "double", "2×", "2-fold"]
        },
        {
            "id": "scaling",
            "description": "Better scaling with data and stages",
            "keywords": ["scale", "scaling", "transformer", "efficiency"]
        }
    ],
    "q11_dna_data_efficiency": [
        {
            "id": "efficiency_gain",
            "description": "Nearly 4x improvement in data efficiency",
            "keywords": ["4x", "four", "4-fold", "nearly 4", "3.9"]
        },
        {
            "id": "domain_targets",
            "description": "Tested on DNA sequence modeling and Chinese text",
            "keywords": ["dna", "chinese", "efficiency"]
        }
    ],
    "q12_character_robustness": [
        {
            "id": "token_drift",
            "description": "Subword tokenizers suffer from catastrophic token drift on typos",
            "keywords": ["drift", "typo", "noise", "perturbation", "robust", "spelling"]
        },
        {
            "id": "byte_preservation",
            "description": "Byte-level modeling preserves root byte representations",
            "keywords": ["byte", "robustness", "character", "token"]
        }
    ]
}

class FactualGrader:
    def __init__(self, verifier: Optional[CitationVerifier] = None):
        self.verifier = verifier or CitationVerifier()
        self._questions_by_id = {q.id: q for q in BENCHMARK_QUESTIONS}

    def _find_matching_question(
        self, query: str, question_id: Optional[str] = None
    ) -> Optional[BenchmarkQuestion]:
        """Find corresponding benchmark question by ID or query string."""
        if question_id and question_id in self._questions_by_id:
            return self._questions_by_id[question_id]

        q_clean = query.strip().lower()
        for bq in BENCHMARK_QUESTIONS:
            if bq.question.strip().lower() == q_clean:
                return bq
            # Partial match for common queries
            if bq.id in q_clean or q_clean in bq.question.lower():
                return bq

        # Concept keyword matching for paraphrased queries
        if "formula" in q_clean and "attention" in q_clean:
            return self._questions_by_id.get("q01_attention_formula")
        if "dimension" in q_clean and ("transformer" in q_clean or "d_model" in q_clean):
            return self._questions_by_id.get("q02_transformer_dimensions")
        if "bleu" in q_clean:
            return self._questions_by_id.get("q03_transformer_bleu")
        if "ffn" in q_clean or "feed-forward" in q_clean:
            return self._questions_by_id.get("q04_ffn_layer")
        if "mimi" in q_clean or ("framerate" in q_clean and "codec" in q_clean):
            return self._questions_by_id.get("q05_mimi_codec_framerate")
        if "latency" in q_clean and "moshi" in q_clean:
            return self._questions_by_id.get("q06_moshi_latency_budget")
        if "multi-stream" in q_clean or "multistream" in q_clean:
            return self._questions_by_id.get("q07_moshi_multistream")
        if "pretrain" in q_clean and "moshi" in q_clean:
            return self._questions_by_id.get("q08_moshi_pretraining_data")
        if "dynamic chunking" in q_clean or ("h-net" in q_clean and "bpe" in q_clean):
            return self._questions_by_id.get("q09_dynamic_chunking_concept")
        if "hierarchy" in q_clean and "h-net" in q_clean:
            return self._questions_by_id.get("q10_hnet_hierarchy_stages")
        if "dna" in q_clean:
            return self._questions_by_id.get("q11_dna_data_efficiency")
        if "robustness" in q_clean or "typo" in q_clean:
            return self._questions_by_id.get("q12_character_robustness")
        if "llama-3" in q_clean or "h100" in q_clean:
            return self._questions_by_id.get("q13_llama3_hardware_infra")
        if "clinical" in q_clean or "patient" in q_clean or "cartesia" in q_clean:
            return self._questions_by_id.get("q14_private_dna_cohorts")
        if "quantum" in q_clean or "d-wave" in q_clean:
            return self._questions_by_id.get("q15_quantum_attention_speedup")

        return None

    def _evaluate_fact_rubric(self, answer: str, rubric: list[dict[str, Any]]) -> tuple[float, list[str], list[str]]:
        """Evaluate answer text against specific fact criteria."""
        ans_lower = answer.lower()
        matched = []
        missing = []
        critical_missing = False

        for crit in rubric:
            cid = crit.get("id", "criterion")
            desc = crit.get("description", cid)
            is_critical = crit.get("critical", False)

            # Check keywords
            kws = crit.get("keywords", [])
            kw_hit = any(kw.lower() in ans_lower for kw in kws) if kws else True

            # Check any_of
            any_of = crit.get("any_of", [])
            any_hit = any(a.lower() in ans_lower for a in any_of) if any_of else True

            # Check scaling_term or additional requirements
            must_also = crit.get("must_also_have", [])
            also_hit = all(m.lower() in ans_lower for m in must_also) if must_also else True

            scaling_terms = crit.get("scaling_term", [])
            scaling_hit = any(s.lower() in ans_lower for s in scaling_terms) if scaling_terms else True

            if kw_hit and any_hit and also_hit and scaling_hit:
                matched.append(desc)
            else:
                missing.append(desc)
                if is_critical:
                    critical_missing = True

        if critical_missing:
            coverage = 0.0
        else:
            coverage = len(matched) / len(rubric) if rubric else 0.0
        return coverage, matched, missing

    def grade_answer(
        self,
        query: str,
        answer: str,
        question_id: Optional[str] = None,
        expected_negative: bool = False,
        ground_truth_key_facts: Optional[list[str]] = None,
        retrieved_chunks: Optional[list[Chunk]] = None,
        status: str = "ok",
        error_message: Optional[str] = None
    ) -> GradeResult:
        """
        Grade response against research-paper ground truth and retrieved citations.
        Explicit grade spectrum:
        - correct: all facts verified + citations valid and grounded in retrieved passages
        - partially_correct: partial fact coverage or valid facts with citation issues
        - wrong (or incorrect): missing required facts, wrong claims, or generic canned reply
        - refused_correctly: unanswerable question properly refused
        - refused_wrongly (or refused_incorrectly): refused answerable question or answered unanswerable
        - unscorable: question lacks verified ground truth annotations
        - error: infrastructure / request failure
        - rate_limited: rate-limited by provider
        """
        chunks = retrieved_chunks or []

        # Step 1: Check infrastructure status
        if status in ("rate_limited",):
            return GradeResult(
                grade="rate_limited",
                details=f"Request rate limited: {error_message}"
            )
        if status in ("error", "timeout") or (error_message and "daily budget" in error_message.lower()):
            if expected_negative and is_explicit_refusal(answer):
                return GradeResult(grade="refused_correctly", is_refusal=True, details="Graceful refusal under budget")
            return GradeResult(
                grade="error",
                details=f"Execution failure: {status} ({error_message})"
            )

        # Step 2: Identify Benchmark Question
        bq = self._find_matching_question(query, question_id)
        effective_expected_negative = bq.expected_negative if bq else expected_negative
        effective_facts = bq.ground_truth_key_facts if bq else (ground_truth_key_facts or [])
        effective_qid = bq.id if bq else (question_id or "")

        is_refusal = is_explicit_refusal(answer)

        # Step 3: Handle Unanswerable / Negative-Control Questions (Q13, Q14, Q15)
        if effective_expected_negative:
            if is_refusal:
                return GradeResult(
                    grade="refused_correctly",
                    is_refusal=True,
                    details="Unanswerable question correctly refused without hallucination"
                )
            else:
                return GradeResult(
                    grade="refused_wrongly",
                    is_refusal=False,
                    details="Model produced an answer for an unanswerable question (hallucination)"
                )

        # Step 4: Handle Refusal on Answerable Question
        if is_refusal:
            return GradeResult(
                grade="refused_wrongly",
                is_refusal=True,
                details="Model refused to answer an answerable benchmark question supported by papers"
            )

        # Step 5: Check Ground Truth Availability
        if not effective_facts and effective_qid not in BENCHMARK_FACT_RUBRICS:
            return GradeResult(
                grade="unscorable",
                details="Question lacks defensible ground-truth annotations; marked as unscorable"
            )

        # Step 6: Verify Citations
        citations_valid, parsed_cits, cit_summary = self.verifier.verify_citations(answer, chunks)
        valid_cits_count = sum(1 for c in parsed_cits if c.resolves_to_corpus and c.resolves_to_page_range)
        grounded_cits_count = sum(1 for c in parsed_cits if c.grounded_in_retrieved)
        total_cits = len(parsed_cits)

        cit_val_ratio = (valid_cits_count / total_cits) if total_cits > 0 else 0.0
        evidence_ratio = (grounded_cits_count / total_cits) if total_cits > 0 else 0.0

        # Step 7: Evaluate Factual Coverage
        if effective_qid in BENCHMARK_FACT_RUBRICS:
            coverage, matched, missing = self._evaluate_fact_rubric(
                answer, BENCHMARK_FACT_RUBRICS[effective_qid]
            )
        else:
            # Generic fact matching for custom questions with ground_truth_key_facts
            ans_lower = answer.lower()
            matched = []
            missing = []
            for fact in effective_facts:
                # Check for significant tokens (length >= 4) or digits
                tokens = [t.lower() for t in re.findall(r"\b\w+\b", fact) if len(t) >= 4 or t.isdigit()]
                hit_count = sum(1 for t in tokens if t in ans_lower)
                if tokens and (hit_count / len(tokens)) >= 0.5:
                    matched.append(fact)
                else:
                    missing.append(fact)
            coverage = len(matched) / len(effective_facts) if effective_facts else 0.0

        # Step 8: Apply Comprehensive Grading Rubric
        # Correct requires: 100% fact coverage AND all citations valid AND grounded in retrieved chunks
        if coverage == 1.0 and total_cits > 0 and grounded_cits_count > 0 and citations_valid:
            grade = "correct"
            details = f"All {len(matched)} facts present with verified citations grounded in retrieved passages."
        elif coverage >= 0.5 and grounded_cits_count > 0 and citations_valid:
            # Covers core facts and has valid grounded citation
            grade = "partially_correct"
            details = f"Partial fact coverage ({coverage:.0%}): matched {len(matched)}, missing {len(missing)}."
        else:
            # Generic answer, wrong claims, missing key facts, or ungrounded/invalid citations
            grade = "wrong"
            details = (
                f"Factual coverage or evidence grounding failed (coverage={coverage:.0%}, "
                f"missing={missing}, grounded_citations={grounded_cits_count}/{total_cits}, valid={citations_valid}). "
                f"Generic, fabricated, or ungrounded claims rejected."
            )

        return GradeResult(
            grade=grade,
            fact_coverage=coverage,
            matched_facts=matched,
            missing_facts=missing,
            citations_verified=parsed_cits,
            citation_validity_ratio=cit_val_ratio,
            evidence_grounded_ratio=evidence_ratio,
            is_refusal=is_refusal,
            details=details
        )

def compute_evaluation_metrics(results: list[Any]) -> dict[str, Any]:
    """
    Compute structured benchmark metrics with explicit denominators.
    Separates answer accuracy, partial correctness, refusal accuracy,
    citation validity, evidence coverage, and execution errors.
    """
    total = len(results)
    if total == 0:
        return {"total_queries": 0, "status": "no_data"}

    # Separate answerable vs unanswerable questions
    answerable = []
    unanswerable = []
    for r in results:
        # Check scenario or expected_negative property
        is_neg = getattr(r, "expected_negative", False) or "q13" in getattr(r, "request_id", "") or "q14" in getattr(r, "request_id", "") or "q15" in getattr(r, "request_id", "")
        if is_neg:
            unanswerable.append(r)
        else:
            answerable.append(r)

    n_ans = len(answerable)
    n_unans = len(unanswerable)

    # Exclude infrastructure execution errors from factual evaluation denominator
    evaluated_answerable = [
        r for r in answerable
        if getattr(r, "status", "") == "ok" and getattr(r, "answer_grade", "") not in ("error", "rate_limited")
    ]
    n_eval_ans = len(evaluated_answerable)

    correct_ans = sum(1 for r in evaluated_answerable if getattr(r, "answer_grade", "") == "correct")
    partial_ans = sum(1 for r in evaluated_answerable if getattr(r, "answer_grade", "") == "partially_correct")
    wrong_ans = sum(1 for r in evaluated_answerable if getattr(r, "answer_grade", "") in ("wrong", "incorrect", "refused_wrongly", "refused_incorrectly"))

    correct_refusals = sum(1 for r in unanswerable if getattr(r, "answer_grade", "") == "refused_correctly")
    wrong_refusals = sum(1 for r in unanswerable if getattr(r, "answer_grade", "") in ("refused_wrongly", "refused_incorrectly", "wrong", "incorrect"))

    errors = sum(1 for r in results if getattr(r, "status", "") in ("error", "timeout") or getattr(r, "answer_grade", "") == "error")
    rate_limited = sum(1 for r in results if getattr(r, "status", "") == "rate_limited" or getattr(r, "answer_grade", "") == "rate_limited")

    # Citations
    all_citations = []
    for r in results:
        all_citations.extend(getattr(r, "citations_found", []))

    return {
        "denominators": {
            "total_queries": total,
            "answerable_queries": n_ans,
            "evaluated_answerable_queries": n_eval_ans,
            "unanswerable_queries": n_unans,
            "total_citations_extracted": len(all_citations)
        },
        "answer_accuracy_pct": round((correct_ans / n_eval_ans) * 100.0, 1) if n_eval_ans > 0 else "N/A",
        "partial_correctness_pct": round((partial_ans / n_eval_ans) * 100.0, 1) if n_eval_ans > 0 else "N/A",
        "wrong_answer_pct": round((wrong_ans / n_eval_ans) * 100.0, 1) if n_eval_ans > 0 else "N/A",
        "refusal_accuracy_pct": round((correct_refusals / n_unans) * 100.0, 1) if n_unans > 0 else "N/A",
        "wrong_refusal_pct": round((wrong_refusals / n_unans) * 100.0, 1) if n_unans > 0 else "N/A",
        "execution_error_pct": round((errors / total) * 100.0, 1),
        "rate_limited_pct": round((rate_limited / total) * 100.0, 1),
        "counts": {
            "correct": correct_ans,
            "partially_correct": partial_ans,
            "wrong": wrong_ans,
            "refused_correctly": correct_refusals,
            "refused_wrongly": wrong_refusals,
            "errors": errors,
            "rate_limited": rate_limited
        }
    }
