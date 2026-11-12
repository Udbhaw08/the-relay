"""
Pipeline Orchestrator for The Relay.
Implements the 4 mandatory steps, tool calling, loop-back/branching, and telemetry tracking.
"""
import time
import re
import random
from typing import Optional, Any, Callable, Generator
from pydantic import BaseModel, Field
from the_relay.config import DEFAULT_SETTING, MAX_RETRIES
from the_relay.retrieval.engine import RetrievalEngine
from the_relay.retrieval.chunker import Chunk
from the_relay.models.router import ModelRouter
from the_relay.models.base import ModelResponse
from the_relay.pipeline.resilience import (
    compute_backoff,
    format_daily_exhaustion_message,
    is_retryable_error,
    parse_retry_after
)
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
    actual_input_tokens: Optional[int] = None
    actual_output_tokens: Optional[int] = None
    actual_total_tokens: Optional[int] = None
    estimated_input_tokens: Optional[int] = None
    estimated_output_tokens: Optional[int] = None
    estimated_total_tokens: Optional[int] = None
    is_simulated: bool = False
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
    queue_wait_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    generation_ms: Optional[float] = None
    verification_ms: Optional[float] = None
    processing_ms: Optional[float] = None
    total_wall_ms: Optional[float] = None
    queue_depth: Optional[int] = None
    concurrency: Optional[int] = None
    timestamps: dict[str, float] = Field(default_factory=dict)

class StreamResultIterator:
    """
    Generator iterator wrapper that yields streaming response chunks in real-time,
    and holds the resulting PipelineResult upon completion in `stream.result`.
    """
    def __init__(self, generator: Generator[str, None, PipelineResult]):
        self._gen = generator
        self.result: Optional[PipelineResult] = None

    def __iter__(self):
        return self

    def __next__(self) -> str:
        try:
            return next(self._gen)
        except StopIteration as e:
            self.result = e.value
            raise

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
            # Immediate refusal branch if no relevant text exists (null TTFT)
            est_in = max(1, len(query.split()))
            return ModelResponse(
                text="The provided research papers do not contain information to answer this question.",
                first_token_ms=None,
                total_ms=0.5,
                tokens_in=est_in,
                tokens_out=15,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=15,
                estimated_total_tokens=est_in + 15,
                is_simulated=(source in ("stand-in", "standin")),
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

    def step_3_stream_reply(
        self, query: str, chunks: list[Chunk], source: str
    ) -> Generator[str, None, tuple[ModelResponse, str]]:
        """Stream a cited response or explicit refusal based strictly on passages."""
        client = self.router.get_client(source)

        if not chunks:
            refusal = "The provided research papers do not contain information to answer this question."
            est_in = max(1, len(query.split()))
            resp = ModelResponse(
                text=refusal,
                first_token_ms=None,
                total_ms=0.5,
                tokens_in=est_in,
                tokens_out=15,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=15,
                estimated_total_tokens=est_in + 15,
                is_simulated=(source in ("stand-in", "standin")),
                provider=source,
                model_name="deterministic_refusal",
                status="ok"
            )
            return resp, refusal

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

        resp = yield from client.stream_generate(prompt=prompt, max_tokens=350)
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
        ground_truth_key_facts: Optional[list[str]] = None,
        queue_wait_ms: Optional[float] = None,
        queue_depth: Optional[int] = None,
        concurrency: Optional[int] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        rng: Optional[random.Random] = None,
        allow_degradation: bool = True
    ) -> PipelineResult:
        """Execute full pipeline for an incoming user question with monotonic component telemetry."""
        sleep_fn = sleeper or time.sleep
        t_req_start_perf = time.perf_counter()
        t_proc_start_perf = t_req_start_perf
        start_time = time.time()
        retries_used = 0
        limit_warning = False
        steps_executed = []
        loop_triggered = False
        degradation_reason = None
        timestamps: dict[str, float] = {
            "request_start_perf": t_req_start_perf,
            "processing_start_perf": t_proc_start_perf
        }
        retrieval_ms_accum = 0.0
        generation_ms_accum = 0.0
        verification_ms_accum = 0.0

        for attempt in range(MAX_RETRIES + 1):
            steps_executed.append("Step 1: Query Parser")
            parsed = self.step_1_parse_query(query)

            # Step 2: Retrieval Tool Call
            steps_executed.append("Step 2: Passage Retrieval Tool")
            t_ret_start = time.perf_counter()
            effective_limit_warning = limit_warning if allow_degradation else False
            chunks, effective_setting = self.step_2_retrieve_tool(
                query=query,
                setting_key=retrieval_setting,
                limit_warning=effective_limit_warning,
                hint=parsed["target_hint"]
            )
            t_ret_end = time.perf_counter()
            retrieval_ms_accum += (t_ret_end - t_ret_start) * 1000.0
            timestamps[f"attempt_{attempt}_retrieval_start"] = t_ret_start
            timestamps[f"attempt_{attempt}_retrieval_end"] = t_ret_end

            if allow_degradation and limit_warning and effective_setting != retrieval_setting:
                degradation_reason = "rate_limit_adaptive_throttle"

            # Step 3: Synthesis
            steps_executed.append("Step 3: Synthesis & Citation")
            t_gen_start = time.perf_counter()
            resp, draft_text = self.step_3_draft_reply(query, chunks, source=source)
            t_gen_end = time.perf_counter()
            generation_ms_accum += (t_gen_end - t_gen_start) * 1000.0
            timestamps[f"attempt_{attempt}_generation_start"] = t_gen_start
            timestamps[f"attempt_{attempt}_generation_end"] = t_gen_end

            # Check for rate limit or errors
            if resp.status != "ok":
                if is_retryable_error(resp.status, resp.error_message) and attempt < MAX_RETRIES:
                    retries_used += 1
                    limit_warning = True  # Throttle down retrieval on retry
                    backoff = compute_backoff(
                        attempt,
                        retry_after_header=resp.rate_limit_headers.get("retry-after"),
                        rng=rng
                    )
                    sleep_fn(backoff)
                    continue
                else:
                    # Non-retryable or budget exhausted
                    t_req_end = time.perf_counter()
                    total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
                    timestamps["completion_perf"] = t_req_end

                    reset_sec = parse_retry_after(resp.rate_limit_headers.get("retry-after"))
                    final_text = (
                        format_daily_exhaustion_message(reset_seconds=reset_sec)
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
                        total_ms=total_wall_ms,
                        total_wall_ms=total_wall_ms,
                        retrieval_ms=round(retrieval_ms_accum, 1),
                        generation_ms=round(generation_ms_accum, 1),
                        verification_ms=None,
                        processing_ms=total_wall_ms,
                        queue_wait_ms=queue_wait_ms,
                        queue_depth=queue_depth,
                        concurrency=concurrency,
                        status=resp.status,
                        retries=retries_used,
                        tokens_in=resp.tokens_in,
                        tokens_out=resp.tokens_out,
                        actual_input_tokens=resp.actual_input_tokens,
                        actual_output_tokens=resp.actual_output_tokens,
                        actual_total_tokens=resp.actual_total_tokens,
                        estimated_input_tokens=resp.estimated_input_tokens,
                        estimated_output_tokens=resp.estimated_output_tokens,
                        estimated_total_tokens=resp.estimated_total_tokens,
                        is_simulated=resp.is_simulated,
                        retrieval_setting=effective_setting,
                        requested_retrieval_setting=retrieval_setting,
                        degradation_reason=degradation_reason,
                        answer_grade=error_grade_res.grade,
                        answer=final_text,
                        steps_executed=steps_executed,
                        loop_triggered=loop_triggered,
                        run_id=run_id,
                        timestamps=timestamps
                    )

            # Step 4: Verification & Hallucination Guard
            steps_executed.append("Step 4: Verification Guard")
            t_ver_start = time.perf_counter()
            is_valid, citations = self.step_4_verify_citations(draft_text, chunks)
            t_ver_end = time.perf_counter()
            verification_ms_accum += (t_ver_end - t_ver_start) * 1000.0
            timestamps[f"attempt_{attempt}_verification_start"] = t_ver_start
            timestamps[f"attempt_{attempt}_verification_end"] = t_ver_end

            # Loop-back Branch: If citations missing or not grounded, re-retrieve once with expanded query
            if not is_valid and not loop_triggered and not parsed["is_unanswerable"] and not is_explicit_refusal(draft_text):
                loop_triggered = True
                steps_executed.append("Loop-back: Expanding retrieval query")
                query = f"{query} technical architecture details"
                continue

            t_req_end = time.perf_counter()
            total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
            timestamps["completion_perf"] = t_req_end

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

            effective_ttft = resp.first_token_ms if (resp.status == "ok" and resp.tokens_out > 0) else None

            return PipelineResult(
                request_id=request_id,
                scenario=scenario,
                source=source,
                start_time=start_time,
                first_token_ms=effective_ttft,
                total_ms=total_wall_ms,
                total_wall_ms=total_wall_ms,
                retrieval_ms=round(retrieval_ms_accum, 1),
                generation_ms=round(generation_ms_accum, 1),
                verification_ms=round(verification_ms_accum, 1),
                processing_ms=total_wall_ms,
                queue_wait_ms=queue_wait_ms,
                queue_depth=queue_depth,
                concurrency=concurrency,
                status="ok",
                retries=retries_used,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                actual_input_tokens=resp.actual_input_tokens,
                actual_output_tokens=resp.actual_output_tokens,
                actual_total_tokens=resp.actual_total_tokens,
                estimated_input_tokens=resp.estimated_input_tokens,
                estimated_output_tokens=resp.estimated_output_tokens,
                estimated_total_tokens=resp.estimated_total_tokens,
                is_simulated=resp.is_simulated,
                retrieval_setting=effective_setting,
                requested_retrieval_setting=retrieval_setting,
                degradation_reason=degradation_reason,
                answer_grade=grade_res.grade,
                answer=draft_text,
                citations_found=citations,
                citation_details=cit_details,
                steps_executed=steps_executed,
                loop_triggered=loop_triggered,
                run_id=run_id,
                timestamps=timestamps
            )

        # Fallback if retry loop finishes without success
        t_req_end = time.perf_counter()
        total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
        timestamps["completion_perf"] = t_req_end
        return PipelineResult(
            request_id=request_id,
            scenario=scenario,
            source=source,
            start_time=start_time,
            first_token_ms=None,
            total_ms=total_wall_ms,
            total_wall_ms=total_wall_ms,
            retrieval_ms=round(retrieval_ms_accum, 1),
            generation_ms=round(generation_ms_accum, 1),
            verification_ms=round(verification_ms_accum, 1),
            processing_ms=total_wall_ms,
            queue_wait_ms=queue_wait_ms,
            queue_depth=queue_depth,
            concurrency=concurrency,
            status="error",
            retries=retries_used,
            tokens_in=0,
            tokens_out=0,
            actual_input_tokens=None,
            actual_output_tokens=None,
            actual_total_tokens=None,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            estimated_total_tokens=0,
            is_simulated=(source in ("stand-in", "standin")),
            retrieval_setting=retrieval_setting,
            requested_retrieval_setting=retrieval_setting,
            degradation_reason=degradation_reason,
            answer_grade="error",
            answer="Pipeline failed after retries.",
            steps_executed=steps_executed,
            run_id=run_id,
            timestamps=timestamps
        )

    # -------------------------------------------------------------
    # Streaming Pipeline Execution
    # -------------------------------------------------------------
    def _run_request_stream_internal(
        self,
        query: str,
        request_id: str,
        scenario: str = "steady",
        source: str = "real",
        retrieval_setting: str = DEFAULT_SETTING,
        expected_negative: bool = False,
        run_id: str = "default_run",
        question_id: Optional[str] = None,
        ground_truth_key_facts: Optional[list[str]] = None,
        queue_wait_ms: Optional[float] = None,
        queue_depth: Optional[int] = None,
        concurrency: Optional[int] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        rng: Optional[random.Random] = None,
        allow_degradation: bool = True
    ) -> Generator[str, None, PipelineResult]:
        """Execute full pipeline yielding stream tokens and returning final PipelineResult."""
        sleep_fn = sleeper or time.sleep
        t_req_start_perf = time.perf_counter()
        t_proc_start_perf = t_req_start_perf
        start_time = time.time()
        retries_used = 0
        limit_warning = False
        steps_executed = []
        loop_triggered = False
        degradation_reason = None
        timestamps: dict[str, float] = {
            "request_start_perf": t_req_start_perf,
            "processing_start_perf": t_proc_start_perf
        }
        retrieval_ms_accum = 0.0
        generation_ms_accum = 0.0
        verification_ms_accum = 0.0
        user_visible_first_token_perf: Optional[float] = None

        for attempt in range(MAX_RETRIES + 1):
            steps_executed.append("Step 1: Query Parser")
            parsed = self.step_1_parse_query(query)

            # Step 2: Retrieval Tool Call
            steps_executed.append("Step 2: Passage Retrieval Tool")
            t_ret_start = time.perf_counter()
            effective_limit_warning = limit_warning if allow_degradation else False
            chunks, effective_setting = self.step_2_retrieve_tool(
                query=query,
                setting_key=retrieval_setting,
                limit_warning=effective_limit_warning,
                hint=parsed["target_hint"]
            )
            t_ret_end = time.perf_counter()
            retrieval_ms_accum += (t_ret_end - t_ret_start) * 1000.0
            timestamps[f"attempt_{attempt}_retrieval_start"] = t_ret_start
            timestamps[f"attempt_{attempt}_retrieval_end"] = t_ret_end

            if allow_degradation and limit_warning and effective_setting != retrieval_setting:
                degradation_reason = "rate_limit_adaptive_throttle"

            # Step 3: Synthesis Stream
            steps_executed.append("Step 3: Synthesis & Citation (Streaming)")
            t_gen_start = time.perf_counter()
            stream_gen = self.step_3_stream_reply(query, chunks, source=source)
            resp = None
            draft_text = ""
            streamed_tokens_in_attempt = 0

            try:
                while True:
                    token_piece = next(stream_gen)
                    if token_piece:
                        if user_visible_first_token_perf is None:
                            user_visible_first_token_perf = time.perf_counter()
                            timestamps["user_visible_first_token_perf"] = user_visible_first_token_perf
                            timestamps["user_visible_ttft_ms"] = round(
                                (user_visible_first_token_perf - t_req_start_perf) * 1000.0, 1
                            )
                        streamed_tokens_in_attempt += 1
                        yield token_piece
            except StopIteration as stop_res:
                if stop_res.value:
                    resp, draft_text = stop_res.value

            t_gen_end = time.perf_counter()
            generation_ms_accum += (t_gen_end - t_gen_start) * 1000.0
            timestamps[f"attempt_{attempt}_generation_start"] = t_gen_start
            timestamps[f"attempt_{attempt}_generation_end"] = t_gen_end

            if resp is None:
                resp = ModelResponse(
                    text="",
                    first_token_ms=None,
                    total_ms=round((t_gen_end - t_gen_start) * 1000.0, 1),
                    tokens_in=0,
                    tokens_out=0,
                    is_simulated=(source in ("stand-in", "standin")),
                    provider=source,
                    model_name="unknown",
                    status="error",
                    error_message="Streaming generator yielded no response object."
                )

            # Check for rate limit or errors
            if resp.status != "ok":
                if is_retryable_error(resp.status, resp.error_message) and attempt < MAX_RETRIES and streamed_tokens_in_attempt == 0:
                    retries_used += 1
                    limit_warning = True
                    backoff = compute_backoff(
                        attempt,
                        retry_after_header=resp.rate_limit_headers.get("retry-after"),
                        rng=rng
                    )
                    sleep_fn(backoff)
                    continue
                else:
                    t_req_end = time.perf_counter()
                    total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
                    timestamps["completion_perf"] = t_req_end

                    reset_sec = parse_retry_after(resp.rate_limit_headers.get("retry-after"))
                    final_text = (
                        format_daily_exhaustion_message(reset_seconds=reset_sec)
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
                        total_ms=total_wall_ms,
                        total_wall_ms=total_wall_ms,
                        retrieval_ms=round(retrieval_ms_accum, 1),
                        generation_ms=round(generation_ms_accum, 1),
                        verification_ms=None,
                        processing_ms=total_wall_ms,
                        queue_wait_ms=queue_wait_ms,
                        queue_depth=queue_depth,
                        concurrency=concurrency,
                        status=resp.status,
                        retries=retries_used,
                        tokens_in=resp.tokens_in,
                        tokens_out=resp.tokens_out,
                        actual_input_tokens=resp.actual_input_tokens,
                        actual_output_tokens=resp.actual_output_tokens,
                        actual_total_tokens=resp.actual_total_tokens,
                        estimated_input_tokens=resp.estimated_input_tokens,
                        estimated_output_tokens=resp.estimated_output_tokens,
                        estimated_total_tokens=resp.estimated_total_tokens,
                        is_simulated=resp.is_simulated,
                        retrieval_setting=effective_setting,
                        requested_retrieval_setting=retrieval_setting,
                        degradation_reason=degradation_reason,
                        answer_grade=error_grade_res.grade,
                        answer=final_text,
                        steps_executed=steps_executed,
                        loop_triggered=loop_triggered,
                        run_id=run_id,
                        timestamps=timestamps
                    )

            # Step 4: Verification & Hallucination Guard
            steps_executed.append("Step 4: Verification Guard")
            t_ver_start = time.perf_counter()
            is_valid, citations = self.step_4_verify_citations(draft_text, chunks)
            t_ver_end = time.perf_counter()
            verification_ms_accum += (t_ver_end - t_ver_start) * 1000.0
            timestamps[f"attempt_{attempt}_verification_start"] = t_ver_start
            timestamps[f"attempt_{attempt}_verification_end"] = t_ver_end

            if not is_valid and not loop_triggered and not parsed["is_unanswerable"] and not is_explicit_refusal(draft_text):
                loop_triggered = True
                steps_executed.append("Loop-back: Verification flagged ungrounded claims")

            t_req_end = time.perf_counter()
            total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
            timestamps["completion_perf"] = t_req_end

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

            effective_ttft = resp.first_token_ms if (resp.status == "ok" and resp.tokens_out > 0) else None

            return PipelineResult(
                request_id=request_id,
                scenario=scenario,
                source=source,
                start_time=start_time,
                first_token_ms=effective_ttft,
                total_ms=total_wall_ms,
                total_wall_ms=total_wall_ms,
                retrieval_ms=round(retrieval_ms_accum, 1),
                generation_ms=round(generation_ms_accum, 1),
                verification_ms=round(verification_ms_accum, 1),
                processing_ms=total_wall_ms,
                queue_wait_ms=queue_wait_ms,
                queue_depth=queue_depth,
                concurrency=concurrency,
                status="ok",
                retries=retries_used,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                actual_input_tokens=resp.actual_input_tokens,
                actual_output_tokens=resp.actual_output_tokens,
                actual_total_tokens=resp.actual_total_tokens,
                estimated_input_tokens=resp.estimated_input_tokens,
                estimated_output_tokens=resp.estimated_output_tokens,
                estimated_total_tokens=resp.estimated_total_tokens,
                is_simulated=resp.is_simulated,
                retrieval_setting=effective_setting,
                requested_retrieval_setting=retrieval_setting,
                degradation_reason=degradation_reason,
                answer_grade=grade_res.grade,
                answer=draft_text,
                citations_found=citations,
                citation_details=cit_details,
                steps_executed=steps_executed,
                loop_triggered=loop_triggered,
                run_id=run_id,
                timestamps=timestamps
            )

        # Fallback if retry loop finishes without success
        t_req_end = time.perf_counter()
        total_wall_ms = max(0.1, round((t_req_end - t_req_start_perf) * 1000.0, 1))
        timestamps["completion_perf"] = t_req_end
        return PipelineResult(
            request_id=request_id,
            scenario=scenario,
            source=source,
            start_time=start_time,
            first_token_ms=None,
            total_ms=total_wall_ms,
            total_wall_ms=total_wall_ms,
            retrieval_ms=round(retrieval_ms_accum, 1),
            generation_ms=round(generation_ms_accum, 1),
            verification_ms=round(verification_ms_accum, 1),
            processing_ms=total_wall_ms,
            queue_wait_ms=queue_wait_ms,
            queue_depth=queue_depth,
            concurrency=concurrency,
            status="error",
            retries=retries_used,
            tokens_in=0,
            tokens_out=0,
            actual_input_tokens=None,
            actual_output_tokens=None,
            actual_total_tokens=None,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            estimated_total_tokens=0,
            is_simulated=(source in ("stand-in", "standin")),
            retrieval_setting=retrieval_setting,
            requested_retrieval_setting=retrieval_setting,
            degradation_reason=degradation_reason,
            answer_grade="error",
            answer="Pipeline failed after retries.",
            steps_executed=steps_executed,
            run_id=run_id,
            timestamps=timestamps
        )

    def run_request_stream(
        self,
        query: str,
        request_id: str,
        scenario: str = "steady",
        source: str = "real",
        retrieval_setting: str = DEFAULT_SETTING,
        expected_negative: bool = False,
        run_id: str = "default_run",
        question_id: Optional[str] = None,
        ground_truth_key_facts: Optional[list[str]] = None,
        queue_wait_ms: Optional[float] = None,
        queue_depth: Optional[int] = None,
        concurrency: Optional[int] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        rng: Optional[random.Random] = None
    ) -> StreamResultIterator:
        """Stream request tokens in real-time, returning a StreamResultIterator whose .result holds PipelineResult."""
        gen = self._run_request_stream_internal(
            query=query,
            request_id=request_id,
            scenario=scenario,
            source=source,
            retrieval_setting=retrieval_setting,
            expected_negative=expected_negative,
            run_id=run_id,
            question_id=question_id,
            ground_truth_key_facts=ground_truth_key_facts,
            queue_wait_ms=queue_wait_ms,
            queue_depth=queue_depth,
            concurrency=concurrency,
            sleeper=sleeper,
            rng=rng
        )
        return StreamResultIterator(gen)

