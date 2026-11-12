"""
Pipeline Orchestrator for The Relay.
Implements the 4 mandatory steps, tool calling, loop-back/branching, and telemetry tracking.
"""
import time
import re
from typing import Optional, Any
from pydantic import BaseModel, Field
from the_relay.config import DEFAULT_SETTING, MAX_RETRIES
from the_relay.retrieval.engine import RetrievalEngine
from the_relay.retrieval.chunker import Chunk
from the_relay.models.router import ModelRouter
from the_relay.models.base import ModelResponse
from the_relay.pipeline.resilience import compute_backoff, format_daily_exhaustion_message, is_retryable_error
from the_relay.eval.grader import CitationVerifier, FactualGrader, is_explicit_refusal

class PipelineResult(BaseModel):
    request_id: str
    scenario: str = "default"
    source: str  # real or stand-in
    start_time: float
    first_token_ms: Optional[float] = None
    total_ms: float
    status: str  # ok, rate_limited, timeout, error
    retries: int
    tokens_in: int
    tokens_out: int
    retrieval_setting: str
    requested_retrieval_setting: Optional[str] = None
    degradation_reason: Optional[str] = None
    answer_grade: str  # correct, partially_correct, wrong, refused_correctly, refused_wrongly, error, rate_limited, unscorable
    answer: str
    citations_found: list[str] = []
    citation_details: list[dict[str, Any]] = Field(default_factory=list)
    steps_executed: list[str] = []
    loop_triggered: bool = False
    run_id: str = "default_run"

class RelayPipeline:
    def __init__(
        self,
        retrieval_engine: Optional[RetrievalEngine] = None,
        router: Optional[ModelRouter] = None,
        citation_verifier: Optional[CitationVerifier] = None,
        factual_grader: Optional[FactualGrader] = None
    ):
        self.retrieval_engine = retrieval_engine or RetrievalEngine()
        self.router = router or ModelRouter()
        self.citation_verifier = citation_verifier or CitationVerifier()
        self.factual_grader = factual_grader or FactualGrader(verifier=self.citation_verifier)

    # -------------------------------------------------------------
    # Step 1: Query Parser & Decomposer
    # -------------------------------------------------------------
    def step_1_parse_query(self, query: str) -> dict:
        """Parse user query to identify key entities and scope."""
        q_clean = query.strip()
        tokens = re.findall(r"\w+", q_clean.lower())
        
        # Out-of-scope check
        out_of_scope_keywords = ["quantum", "llama-3", "gpt-4", "financial market", "dna private sequencing"]
        is_potentially_unanswerable = any(k in q_clean.lower() for k in out_of_scope_keywords)
        
        # Identify possible target paper
        hint = None
        if any(w in tokens for w in ["moshi", "speech", "audio", "mimi", "codec"]):
            hint = "Moshi"
        elif any(w in tokens for w in ["chunking", "h-net", "byte", "hierarchical"]):
            hint = "Dynamic Chunking"
        elif any(w in tokens for w in ["attention", "transformer", "vaswani", "bleu", "multi-head"]):
            hint = "Attention Is All You Need"

        return {
            "cleaned_query": q_clean,
            "target_hint": hint,
            "is_unanswerable": is_potentially_unanswerable
        }

    # -------------------------------------------------------------
    # Step 2: Tool Call - Passage Retrieval
    # -------------------------------------------------------------
    def step_2_retrieve_tool(
        self, query: str, setting_key: str, limit_warning: bool, hint: Optional[str]
    ) -> tuple[list[Chunk], str]:
        """Tool call to retrieve top matching passages from research paper index."""
        return self.retrieval_engine.retrieve(
            query=query,
            setting_key=setting_key,
            limit_warning=limit_warning,
            target_paper_hint=hint
        )

    # -------------------------------------------------------------
    # Step 3: Synthesis & Citation Drafter
    # -------------------------------------------------------------
    def step_3_draft_reply(
        self, query: str, chunks: list[Chunk], source: str
    ) -> tuple[ModelResponse, str]:
        """Draft a cited response or explicit refusal based strictly on passages."""
        client = self.router.get_client(source)
        
        if not chunks:
            # Immediate refusal branch if no relevant text exists
            return ModelResponse(
                text="The provided research papers do not contain information to answer this question.",
                first_token_ms=20.0,
                total_ms=25.0,
                tokens_in=len(query.split()),
                tokens_out=15,
                provider=source,
                model_name="deterministic_refusal",
                status="ok"
            ), "The provided research papers do not contain information to answer this question."

        context_str = self.retrieval_engine.format_context_prompt(chunks)
        prompt = (
            f"You are a research assistant answering technical questions strictly from the provided papers.\n"
            f"Context passages:\n{context_str}\n\n"
            f"User Question: {query}\n\n"
            f"Instructions:\n"
            f"1. Answer the question using ONLY the provided passages.\n"
            f"2. Cite the exact paper title, page, and section for each claim: [Paper, Page X, Section Y].\n"
            f"3. If the passages do not state the answer, reply strictly: 'The provided papers do not say.'\n"
            f"Answer:"
        )

        resp = client.generate(prompt=prompt, max_tokens=350)
        return resp, resp.text

    # -------------------------------------------------------------
    # Step 4: Verification & Hallucination Guard (Loop/Branch)
    # -------------------------------------------------------------
    def step_4_verify_citations(self, draft_text: str, chunks: list[Chunk]) -> tuple[bool, list[str]]:
        """
        Verifies that citations in draft_text are grounded in retrieved chunks.
        Returns (is_valid, extracted_citations).
        """
        if is_explicit_refusal(draft_text):
            return True, []
        is_valid, parsed_cits, _ = self.citation_verifier.verify_citations(draft_text, chunks)
        citations_found = [c.raw for c in parsed_cits]
        return is_valid, citations_found

    # -------------------------------------------------------------
    # Pipeline Execution with Resilience & Retries
    # -------------------------------------------------------------
    def run_request(
        self,
        query: str,
        request_id: str,
        scenario: str = "steady",
        source: str = "real",
        retrieval_setting: str = DEFAULT_SETTING,
        expected_negative: bool = False,
        run_id: str = "default_run",
        question_id: Optional[str] = None,
        ground_truth_key_facts: Optional[list[str]] = None
    ) -> PipelineResult:
        """Execute full pipeline for an incoming user question."""
        start_time = time.time()
        retries_used = 0
        limit_warning = False
        steps_executed = []
        loop_triggered = False
        degradation_reason = None

        for attempt in range(MAX_RETRIES + 1):
            steps_executed.append("Step 1: Query Parser")
            parsed = self.step_1_parse_query(query)

            # Step 2: Retrieval Tool Call
            steps_executed.append("Step 2: Passage Retrieval Tool")
            chunks, effective_setting = self.step_2_retrieve_tool(
                query=query,
                setting_key=retrieval_setting,
                limit_warning=limit_warning,
                hint=parsed["target_hint"]
            )
            if limit_warning and effective_setting != retrieval_setting:
                degradation_reason = "rate_limit_adaptive_throttle"

            # Step 3: Synthesis
            steps_executed.append("Step 3: Synthesis & Citation")
            resp, draft_text = self.step_3_draft_reply(query, chunks, source=source)

            # Check for rate limit or errors
            if resp.status != "ok":
                if is_retryable_error(resp.status, resp.error_message) and attempt < MAX_RETRIES:
                    retries_used += 1
                    limit_warning = True  # Throttle down retrieval on retry
                    backoff = compute_backoff(
                        attempt,
                        retry_after_header=resp.rate_limit_headers.get("retry-after")
                    )
                    time.sleep(backoff)
                    continue
                else:
                    # Non-retryable or budget exhausted
                    final_text = (
                        format_daily_exhaustion_message()
                        if "daily budget" in (resp.error_message or "").lower()
                        else f"Service unavailable: {resp.error_message}"
                    )
                    error_grade_res = self.factual_grader.grade_answer(
                        query=query,
                        answer=final_text,
                        question_id=question_id,
                        expected_negative=expected_negative,
                        ground_truth_key_facts=ground_truth_key_facts,
                        retrieved_chunks=chunks,
                        status=resp.status,
                        error_message=resp.error_message
                    )
                    return PipelineResult(
                        request_id=request_id,
                        scenario=scenario,
                        source=source,
                        start_time=start_time,
                        first_token_ms=None,
                        total_ms=resp.total_ms,
                        status=resp.status,
                        retries=retries_used,
                        tokens_in=resp.tokens_in,
                        tokens_out=resp.tokens_out,
                        retrieval_setting=effective_setting,
                        requested_retrieval_setting=retrieval_setting,
                        degradation_reason=degradation_reason,
                        answer_grade=error_grade_res.grade,
                        answer=final_text,
                        steps_executed=steps_executed,
                        loop_triggered=loop_triggered,
                        run_id=run_id
                    )

            # Step 4: Verification & Hallucination Guard
            steps_executed.append("Step 4: Verification Guard")
            is_valid, citations = self.step_4_verify_citations(draft_text, chunks)

            # Loop-back Branch: If citations missing or not grounded, re-retrieve once with expanded query
            if not is_valid and not loop_triggered and not parsed["is_unanswerable"] and not is_explicit_refusal(draft_text):
                loop_triggered = True
                steps_executed.append("Loop-back: Expanding retrieval query")
                query = f"{query} technical architecture details"
                continue

            # Factual grading and evidence-based verification
            grade_res = self.factual_grader.grade_answer(
                query=query,
                answer=draft_text,
                question_id=question_id,
                expected_negative=expected_negative,
                ground_truth_key_facts=ground_truth_key_facts,
                retrieved_chunks=chunks,
                status="ok"
            )

            cit_details = [
                {
                    "raw": c.raw,
                    "paper_id": c.paper_id,
                    "paper_title": c.paper_title,
                    "page_number": c.page_number,
                    "section": c.section,
                    "chunk_id": c.chunk_id,
                    "resolves_to_corpus": c.resolves_to_corpus,
                    "resolves_to_page_range": c.resolves_to_page_range,
                    "grounded_in_retrieved": c.grounded_in_retrieved,
                    "supports_evidence": c.supports_evidence,
                    "details": c.details
                }
                for c in grade_res.citations_verified
            ]

            return PipelineResult(
                request_id=request_id,
                scenario=scenario,
                source=source,
                start_time=start_time,
                first_token_ms=resp.first_token_ms if resp.tokens_out > 0 else None,
                total_ms=resp.total_ms,
                status="ok",
                retries=retries_used,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                retrieval_setting=effective_setting,
                requested_retrieval_setting=retrieval_setting,
                degradation_reason=degradation_reason,
                answer_grade=grade_res.grade,
                answer=draft_text,
                citations_found=citations,
                citation_details=cit_details,
                steps_executed=steps_executed,
                loop_triggered=loop_triggered,
                run_id=run_id
            )

        # Fallback if retry loop finishes without success
        return PipelineResult(
            request_id=request_id,
            scenario=scenario,
            source=source,
            start_time=start_time,
            first_token_ms=None,
            total_ms=0.0,
            status="error",
            retries=retries_used,
            tokens_in=0,
            tokens_out=0,
            retrieval_setting=retrieval_setting,
            requested_retrieval_setting=retrieval_setting,
            degradation_reason=degradation_reason,
            answer_grade="error",
            answer="Pipeline failed after retries.",
            steps_executed=steps_executed,
            run_id=run_id
        )

