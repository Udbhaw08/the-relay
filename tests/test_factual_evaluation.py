"""
Unit and integration tests for Phase 3:
Factual answer evaluation, evidence-based citation verification, and explicit grade rubrics.
"""
import pytest
from the_relay.eval.grader import (
    CitationVerifier,
    FactualGrader,
    is_explicit_refusal,
    compute_evaluation_metrics
)
from the_relay.retrieval.chunker import Chunk
from the_relay.eval.benchmark_questions import BenchmarkQuestion
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult

@pytest.fixture
def sample_retrieved_chunks():
    return [
        Chunk(
            chunk_id="1706.03762v7_p4_c7",
            paper_id="1706.03762v7",
            paper_title="Attention Is All You Need",
            page_number=4,
            section="3.2.1 Scaled Dot-Product Attention",
            text="Attention(Q, K, V) = softmax(QK^T / sqrt(d_k))V. Dot products grow large in magnitude, pushing softmax into small gradients.",
            token_count=60
        ),
        Chunk(
            chunk_id="1706.03762v7_p8_c15",
            paper_id="1706.03762v7",
            paper_title="Attention Is All You Need",
            page_number=8,
            section="5.1 Machine Translation",
            text="On the WMT 2014 English-to-German translation task, the big transformer model achieves 28.4 BLEU. On English-to-French, it achieves 41.8 BLEU.",
            token_count=75
        ),
        Chunk(
            chunk_id="2410.00037v1_p4_c10",
            paper_id="2410.00037v1",
            paper_title="Moshi: a speech-text foundation model for real-time dialogue",
            page_number=4,
            section="2 Architecture",
            text="Moshi utilizes the Mimi neural audio codec operating at 12.5 Hz framerate with 8 codebooks, achieving 160ms theoretical conversational latency.",
            token_count=65
        ),
        Chunk(
            chunk_id="2410.00037v1_p6_c12",
            paper_id="2410.00037v1",
            paper_title="Moshi: a speech-text foundation model for real-time dialogue",
            page_number=6,
            section="3 Pre-training",
            text="The 7B parameter foundation model Helena was pretrained on both speech and text tokens.",
            token_count=70
        )
    ]

def test_factually_correct_answer_with_valid_citation_passes(sample_retrieved_chunks):
    grader = FactualGrader()
    ans = (
        "The base Transformer Scaled Dot-Product Attention is computed as softmax(QK^T / sqrt(d_k))V. "
        "The scaling factor 1/sqrt(d_k) counteracts large dot products pushing the softmax function into small gradients. "
        "Citation: [Attention Is All You Need, Page 4, Section 3.2.1]."
    )
    res = grader.grade_answer(
        query="What is the exact mathematical formula for Scaled Dot-Product Attention, and why is the scaling factor 1/sqrt(d_k) used?",
        answer=ans,
        question_id="q01_attention_formula",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade == "correct"
    assert res.fact_coverage == 1.0
    assert res.citation_validity_ratio == 1.0
    assert res.evidence_grounded_ratio == 1.0

def test_incorrect_facts_with_valid_citation_fails(sample_retrieved_chunks):
    grader = FactualGrader()
    # Wrong BLEU scores
    ans = (
        "The big Transformer model achieved a BLEU score of 12.5 on English-to-German and 18.2 on English-to-French. "
        "Citation: [Attention Is All You Need, Page 8, Section 5.1]."
    )
    res = grader.grade_answer(
        query="What BLEU score did the big Transformer model achieve on WMT 2014?",
        answer=ans,
        question_id="q03_transformer_bleu",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade in ("wrong", "incorrect")
    assert res.fact_coverage == 0.0

def test_generic_answer_with_citation_fails_q03(sample_retrieved_chunks):
    """Problematic case 1: Generic BLEU response with citation must fail."""
    grader = FactualGrader()
    generic_ans = (
        "The Transformer architecture achieved state-of-the-art BLEU scores on translation tasks across benchmarks. "
        "Citation: [Attention Is All You Need, Page 8, Section 5.1]."
    )
    res = grader.grade_answer(
        query="What BLEU score did the big Transformer model achieve on the WMT 2014 English-to-German and English-to-French translation benchmarks?",
        answer=generic_ans,
        question_id="q03_transformer_bleu",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade in ("wrong", "incorrect")
    assert res.fact_coverage == 0.0
    assert "missing" in res.details.lower()

def test_specific_bleu_scores_pass_q03(sample_retrieved_chunks):
    """Specific BLEU numbers 28.4 and 41.8 must pass."""
    grader = FactualGrader()
    specific_ans = (
        "The big Transformer model achieved 28.4 BLEU on English-to-German and 41.8 BLEU on English-to-French. "
        "Citation: [Attention Is All You Need, Page 8, Section 5.1]."
    )
    res = grader.grade_answer(
        query="What BLEU score did the big Transformer model achieve on the WMT 2014 English-to-German and English-to-French translation benchmarks?",
        answer=specific_ans,
        question_id="q03_transformer_bleu",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade == "correct"
    assert res.fact_coverage == 1.0

def test_generic_answer_with_citation_fails_q08(sample_retrieved_chunks):
    """Problematic case 2: Moshi foundation model size generic reply must fail."""
    grader = FactualGrader()
    generic_moshi = (
        "Moshi is a foundation model trained on speech and conversational audio datasets. "
        "Citation: [Moshi: a speech-text foundation model for real-time dialogue, Page 4, Section 2]."
    )
    res = grader.grade_answer(
        query="What is the total size of the foundation model and how many tokens/hours was Moshi pretrained on?",
        answer=generic_moshi,
        question_id="q08_moshi_pretraining_data",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade in ("wrong", "incorrect")
    assert res.fact_coverage < 1.0

def test_specific_moshi_size_passes_q08(sample_retrieved_chunks):
    """Moshi 7B parameter (Helena) must pass."""
    grader = FactualGrader()
    specific_moshi = (
        "Moshi is built upon a 7B parameter foundation model named Helena, pre-trained on text and speech data. "
        "Citation: [Moshi: a speech-text foundation model for real-time dialogue, Page 6, Section 3]."
    )
    res = grader.grade_answer(
        query="What is the total size of the foundation model and how many tokens/hours was Moshi pretrained on?",
        answer=specific_moshi,
        question_id="q08_moshi_pretraining_data",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade == "correct"
    assert res.fact_coverage == 1.0

def test_correct_facts_with_unrelated_paper_citation_fails(sample_retrieved_chunks):
    """Claim contains facts, but cites an unrelated paper."""
    grader = FactualGrader()
    ans = (
        "The big Transformer achieved 28.4 BLEU on English-to-German and 41.8 BLEU on English-to-French. "
        "Citation: [Moshi: a speech-text foundation model for real-time dialogue, Page 4, Section 2]."
    )
    res = grader.grade_answer(
        query="What BLEU score did the big Transformer model achieve on WMT 2014?",
        answer=ans,
        question_id="q03_transformer_bleu",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade in ("wrong", "incorrect")
    assert res.evidence_grounded_ratio == 0.0

def test_nonexistent_page_citation_fails(sample_retrieved_chunks):
    """Page 99 does not exist in 15-page Attention paper."""
    grader = FactualGrader()
    ans = (
        "Scaled Dot-Product Attention is softmax(QK^T / sqrt(d_k))V to prevent large dot products pushing into small gradients. "
        "Citation: [Attention Is All You Need, Page 99, Section 3.2]."
    )
    res = grader.grade_answer(
        query="What is the formula for scaled dot-product attention?",
        answer=ans,
        question_id="q01_attention_formula",
        retrieved_chunks=sample_retrieved_chunks
    )
    assert res.grade in ("wrong", "incorrect")
    assert res.citation_validity_ratio == 0.0

def test_unindexed_paper_citation_fails(sample_retrieved_chunks):
    """Citation to an invented paper outside the 3 indexed papers."""
    verifier = CitationVerifier()
    parsed = verifier.parse_and_verify_citation(
        "Llama-3 Architecture Whitepaper, Page 12",
        sample_retrieved_chunks
    )
    assert not parsed.resolves_to_corpus
    assert "unindexed" in parsed.details.lower() or "invented" in parsed.details.lower()

def test_correct_refusal_for_unanswerable_question():
    """Unanswerable negative control (Q13) properly refused."""
    grader = FactualGrader()
    refusal = "The provided research papers do not contain information regarding Llama-3 GPU cluster topology."
    res = grader.grade_answer(
        query="What specific 16,000 H100 GPU cluster networking topology was used to train the Llama-3 405B base model?",
        answer=refusal,
        question_id="q13_llama3_hardware_infra",
        expected_negative=True
    )
    assert res.grade == "refused_correctly"
    assert res.is_refusal

def test_unsupported_confident_answer_fails_on_negative_control():
    """Model invents an answer for an unanswerable question (hallucination)."""
    grader = FactualGrader()
    hallucination = "The cluster used 16,000 H100 GPUs connected via 3.2 Tbps InfiniBand networks. [Attention Is All You Need, Page 3]"
    res = grader.grade_answer(
        query="What specific 16,000 H100 GPU cluster networking topology was used to train the Llama-3 405B base model?",
        answer=hallucination,
        question_id="q13_llama3_hardware_infra",
        expected_negative=True
    )
    assert res.grade in ("refused_wrongly", "refused_incorrectly")
    assert not res.is_refusal

def test_refusal_on_answerable_question_fails():
    """Model refuses an answerable question supported by papers."""
    grader = FactualGrader()
    refusal = "The provided research papers do not contain information regarding this topic."
    res = grader.grade_answer(
        query="What is the exact mathematical formula for Scaled Dot-Product Attention?",
        answer=refusal,
        question_id="q01_attention_formula",
        expected_negative=False
    )
    assert res.grade in ("refused_wrongly", "refused_incorrectly")

def test_missing_ground_truth_is_unscorable():
    """Question without ground truth annotations must be unscorable, not automatically correct."""
    grader = FactualGrader()
    ans = "The weather today in Kyoto is clear and sunny. [Attention Is All You Need, Page 1]"
    res = grader.grade_answer(
        query="What is the weather in Kyoto today?",
        answer=ans,
        expected_negative=False
    )
    assert res.grade == "unscorable"
    assert "unscorable" in res.details.lower()

def test_evaluation_metrics_denominator_correctness():
    """Metrics calculator must exclude errors from accuracy denominators and report all counts."""
    results = [
        PipelineResult(request_id="eval_q01", source="stand-in", start_time=1.0, total_ms=10.0, status="ok", retries=0, tokens_in=10, tokens_out=20, retrieval_setting="setting_b", answer_grade="correct", answer="ok", citations_found=["[Attention, Page 4]"]),
        PipelineResult(request_id="eval_q03", source="stand-in", start_time=1.0, total_ms=10.0, status="ok", retries=0, tokens_in=10, tokens_out=20, retrieval_setting="setting_b", answer_grade="wrong", answer="bad", citations_found=["[Attention, Page 4]"]),
        PipelineResult(request_id="eval_q13", source="stand-in", start_time=1.0, total_ms=10.0, status="ok", retries=0, tokens_in=10, tokens_out=20, retrieval_setting="setting_b", answer_grade="refused_correctly", answer="refused"),
        PipelineResult(request_id="eval_q14", source="stand-in", start_time=1.0, total_ms=10.0, status="ok", retries=0, tokens_in=10, tokens_out=20, retrieval_setting="setting_b", answer_grade="refused_wrongly", answer="invented", citations_found=["[Attention, Page 4]"]),
        PipelineResult(request_id="eval_q02_err", source="stand-in", start_time=1.0, total_ms=10.0, status="error", retries=0, tokens_in=0, tokens_out=0, retrieval_setting="setting_b", answer_grade="error", answer="failed")
    ]
    metrics = compute_evaluation_metrics(results)

    # Denominators
    denoms = metrics["denominators"]
    assert denoms["total_queries"] == 5
    assert denoms["answerable_queries"] == 3
    assert denoms["evaluated_answerable_queries"] == 2  # q02_err excluded from factual denominator!
    assert denoms["unanswerable_queries"] == 2

    # Ratios
    assert metrics["answer_accuracy_pct"] == 50.0  # 1 correct out of 2 evaluated
    assert metrics["wrong_answer_pct"] == 50.0  # 1 wrong out of 2 evaluated
    assert metrics["refusal_accuracy_pct"] == 50.0  # 1 correct refusal out of 2 unanswerable
    assert metrics["execution_error_pct"] == 20.0  # 1 error out of 5 total

def test_pipeline_citation_provenance_integration():
    """Orchestrator pipeline preserves structured citation provenance details."""
    pipe = RelayPipeline()
    pipe.router.stand_in_client.fast_mode = True
    res = pipe.run_request(
        query="What is the exact mathematical formula for Scaled Dot-Product Attention, and why is the scaling factor 1/sqrt(d_k) used?",
        request_id="test_prov_01",
        source="stand-in",
        retrieval_setting="setting_b",
        question_id="q01_attention_formula"
    )
    assert res.status == "ok"
    assert res.answer_grade == "correct"
    assert len(res.citations_found) > 0
    assert len(res.citation_details) > 0
    # Provenance fields present
    first_cit = res.citation_details[0]
    assert first_cit["paper_id"] == "1706.03762v7"
    assert first_cit["page_number"] == 4
    assert first_cit["grounded_in_retrieved"] is True
