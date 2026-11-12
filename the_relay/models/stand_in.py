"""
Calibrated Stand-In Model Service.
Mimics real hosted LLM behavior, queueing delay under load, token-bucket rate limits,
intermittent failures, and piece-by-piece streaming generation.
"""
import time
import random
import threading
from typing import Generator, Optional
from collections import deque
from the_relay.models.base import BaseModelClient, ModelResponse

class StandInModelClient(BaseModelClient):
    def __init__(
        self,
        rpm_limit: int = 15,
        tpm_limit: int = 1000000,
        rpd_limit: int = 1500,
        base_ttft_ms: float = 1200.0,
        ttft_std_ms: float = 300.0,
        ms_per_token: float = 15.0,
        failure_rate: float = 0.02,
        timeout_rate: float = 0.01,
        concurrency_penalty_factor: float = 0.08,
        random_seed: Optional[int] = None,
        fast_mode: bool = False
    ):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.rpd_limit = rpd_limit
        self.fast_mode = fast_mode
        
        # Calibrated latency distribution parameters
        self.base_ttft_ms = base_ttft_ms
        self.ttft_std_ms = ttft_std_ms
        self.ms_per_token = ms_per_token
        self.failure_rate = failure_rate
        self.timeout_rate = timeout_rate
        self.concurrency_penalty = concurrency_penalty_factor
        
        # Seeded random generator for reproducible simulation
        self.random_seed = random_seed
        self._rng = random.Random(random_seed) if random_seed is not None else random.Random()

        # State tracking
        self._lock = threading.Lock()
        self._in_flight = 0
        self._max_concurrency = 0
        self._queue_depth = 0
        self._peak_queue_depth = 0
        self._peak_queue_length = 0  # legacy alias for max_concurrency
        self._request_timestamps = deque()
        self._daily_request_count = 0
        self._daily_budget_exhausted = False
        self._tpm_exhausted = False
        self._injected_fault: Optional[str] = None

    def set_seed(self, seed: Optional[int]):
        """Set random seed for deterministic simulation."""
        self.random_seed = seed
        self._rng = random.Random(seed) if seed is not None else random.Random()

    def reset_quota_state(self):
        """Reset internal rate limiters, timestamps, daily counts, in-flight, and queue counters."""
        with self._lock:
            self._request_timestamps.clear()
            self._daily_request_count = 0
            self._daily_budget_exhausted = False
            self._tpm_exhausted = False
            self._injected_fault = None
            self._in_flight = 0
            self._max_concurrency = 0
            self._queue_depth = 0
            self._peak_queue_depth = 0
            self._peak_queue_length = 0

    def inject_fault(self, fault_type: str):
        """Deterministically inject simulated failure: '429', 'timeout', 'network_failure', '500'."""
        with self._lock:
            self._injected_fault = fault_type.lower()

    def clear_injected_faults(self):
        """Clear any injected faults or exhaustion overrides."""
        with self._lock:
            self._injected_fault = None
            self._tpm_exhausted = False
            self._daily_budget_exhausted = False

    def exhaust_rpm(self):
        """Force stand-in into RPM limit exceeded state."""
        with self._lock:
            now = time.time()
            self._request_timestamps = deque([now] * self.rpm_limit)

    def exhaust_tpm(self):
        """Force stand-in into TPM limit exceeded state."""
        with self._lock:
            self._tpm_exhausted = True

    def queue_enter(self) -> int:
        """Record entry of a request into the waiting queue."""
        with self._lock:
            self._queue_depth += 1
            if self._queue_depth > self._peak_queue_depth:
                self._peak_queue_depth = self._queue_depth
            return self._queue_depth

    def queue_exit(self) -> int:
        """Record departure of a request from the waiting queue into execution."""
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)
            return self._queue_depth

    def get_concurrency_stats(self) -> dict[str, int]:
        """Return independent measurements of in-flight concurrency and queue depth."""
        with self._lock:
            return {
                "in_flight": self._in_flight,
                "max_concurrency": self._max_concurrency,
                "queue_depth": self._queue_depth,
                "peak_queue_depth": self._peak_queue_depth
            }

    def exhaust_daily_budget(self):
        """Force stand-in into daily budget exhausted state (for Scenario 5)."""
        with self._lock:
            self._daily_budget_exhausted = True

    def halve_rpm_limit(self):
        """Halve the RPM limit (for Scenario 4)."""
        with self._lock:
            self.rpm_limit = max(1, self.rpm_limit // 2)

    def _check_rate_limits(self, now: float) -> Optional[tuple[str, dict[str, str]]]:
        """Check if RPM, TPM, RPD, or injected faults are triggered. Returns (error_type, headers)."""
        with self._lock:
            if self._injected_fault:
                if self._injected_fault in ("429", "rate_limited"):
                    return "rate_limited", {
                        "error": "Simulated rate limit exceeded (HTTP 429)",
                        "retry-after": "5",
                        "x-ratelimit-remaining-requests": "0"
                    }
                elif self._injected_fault == "timeout":
                    return "timeout", {
                        "error": "Simulated gateway timeout",
                        "status_code": "504"
                    }
                elif self._injected_fault in ("500", "server_error", "network_failure"):
                    return "error", {
                        "error": "Simulated 500 internal server error",
                        "status_code": "500"
                    }

            if self._daily_budget_exhausted or self._daily_request_count >= self.rpd_limit:
                return "rate_limited", {
                    "error": "Daily budget exhausted",
                    "retry-after": "43200",  # 12 hours until reset
                    "x-ratelimit-remaining-requests": "0"
                }

            if self._tpm_exhausted:
                return "rate_limited", {
                    "error": "Token limit exceeded (TPM)",
                    "retry-after": "20",
                    "x-ratelimit-remaining-tokens": "0"
                }

            # Clean timestamps older than 60 seconds
            while self._request_timestamps and now - self._request_timestamps[0] > 60.0:
                self._request_timestamps.popleft()

            if len(self._request_timestamps) >= self.rpm_limit:
                retry_wait = max(1, int(60.0 - (now - self._request_timestamps[0])))
                return "rate_limited", {
                    "error": f"Rate limit exceeded ({self.rpm_limit} RPM)",
                    "retry-after": str(retry_wait),
                    "x-ratelimit-remaining-requests": "0"
                }

            # Request accepted
            self._request_timestamps.append(now)
            self._daily_request_count += 1
            remaining = str(self.rpm_limit - len(self._request_timestamps))
            return None, {"x-ratelimit-remaining-requests": remaining}

    def _compute_calibrated_delay(self, tokens_out: int) -> tuple[float, float]:
        """Calculate TTFT and total generation delay with concurrency penalty."""
        with self._lock:
            in_flight = self._in_flight
        
        # Log-normal jitter around base TTFT
        raw_ttft = max(150.0, self._rng.gauss(self.base_ttft_ms, self.ttft_std_ms))
        
        # Concurrency queueing penalty: delay scales non-linearly with in-flight load
        load_multiplier = 1.0 + (self.concurrency_penalty * (in_flight ** 1.15))
        calibrated_ttft = raw_ttft * load_multiplier
        
        gen_time = (tokens_out * self.ms_per_token) * (1.0 + (in_flight * 0.02))
        return calibrated_ttft, gen_time

    def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> ModelResponse:
        """Synchronously simulate request execution with calibrated delays."""
        t0 = time.time()
        start_perf = time.perf_counter()
        tokens_in = max(1, len(prompt.split()) * 4 // 3)

        # Check rate limits
        limit_error, headers = self._check_rate_limits(t0)
        if limit_error == "rate_limited":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="rate_limited",
                error_message=headers.get("error", "Rate limit reached"),
                rate_limit_headers=headers
            )
        elif limit_error == "timeout":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="timeout",
                error_message=headers.get("error", "Gateway timeout"),
                rate_limit_headers=headers
            )
        elif limit_error == "error":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="error",
                error_message=headers.get("error", "Internal server error"),
                rate_limit_headers=headers
            )

        with self._lock:
            self._in_flight += 1
            if self._in_flight > self._max_concurrency:
                self._max_concurrency = self._in_flight
                self._peak_queue_length = self._in_flight

        try:
            # Simulate random network fault / timeout
            roll = self._rng.random()
            if roll < self.timeout_rate:
                time.sleep(0.5)  # simulate hanging call
                total_ms = (time.perf_counter() - start_perf) * 1000.0
                return ModelResponse(
                    text="",
                    first_token_ms=None,
                    total_ms=round(total_ms, 1),
                    tokens_in=tokens_in,
                    tokens_out=0,
                    actual_input_tokens=None,
                    actual_output_tokens=None,
                    actual_total_tokens=None,
                    estimated_input_tokens=tokens_in,
                    estimated_output_tokens=0,
                    estimated_total_tokens=tokens_in,
                    is_simulated=True,
                    provider="stand_in",
                    model_name="stand-in-calibrated-v1",
                    status="timeout",
                    error_message="Gateway timeout",
                    rate_limit_headers=headers
                )
            elif roll < (self.timeout_rate + self.failure_rate):
                total_ms = (time.perf_counter() - start_perf) * 1000.0
                return ModelResponse(
                    text="",
                    first_token_ms=None,
                    total_ms=round(total_ms, 1),
                    tokens_in=tokens_in,
                    tokens_out=0,
                    actual_input_tokens=None,
                    actual_output_tokens=None,
                    actual_total_tokens=None,
                    estimated_input_tokens=tokens_in,
                    estimated_output_tokens=0,
                    estimated_total_tokens=tokens_in,
                    is_simulated=True,
                    provider="stand_in",
                    model_name="stand-in-calibrated-v1",
                    status="error",
                    error_message="Internal server error 500",
                    rate_limit_headers=headers
                )

            # Generate synthetic content
            simulated_text = self._synthesize_mock_reply(prompt)
            tokens_out = max(15, len(simulated_text.split()) * 4 // 3)
            tokens_in = max(10, len(prompt.split()) * 4 // 3)

            ttft_ms, gen_ms = self._compute_calibrated_delay(tokens_out)

            # Apply simulated sleeping (bypassed in fast_mode for unit tests)
            if not self.fast_mode:
                sleep_ttft = min(ttft_ms / 1000.0, 3.0)
                time.sleep(sleep_ttft)
                sleep_gen = min(gen_ms / 1000.0, 2.0)
                time.sleep(sleep_gen)

            actual_total_ms = (time.perf_counter() - start_perf) * 1000.0

            return ModelResponse(
                text=simulated_text,
                first_token_ms=round(ttft_ms, 1),
                total_ms=round(ttft_ms + gen_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=tokens_out,
                estimated_total_tokens=tokens_in + tokens_out,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="ok",
                rate_limit_headers=headers
            )
        finally:
            with self._lock:
                self._in_flight = max(0, self._in_flight - 1)

    def stream_generate(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000
    ) -> Generator[str, None, ModelResponse]:
        """Stream piece-by-piece emulation."""
        t0 = time.time()
        start_perf = time.perf_counter()
        tokens_in = max(1, len(prompt.split()) * 4 // 3)

        limit_error, headers = self._check_rate_limits(t0)
        if limit_error == "rate_limited":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="rate_limited",
                error_message=headers.get("error", "Rate limit reached"),
                rate_limit_headers=headers
            )
        elif limit_error == "timeout":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="timeout",
                error_message=headers.get("error", "Gateway timeout"),
                rate_limit_headers=headers
            )
        elif limit_error == "error":
            total_ms = (time.perf_counter() - start_perf) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=0,
                estimated_total_tokens=tokens_in,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="error",
                error_message=headers.get("error", "Internal server error"),
                rate_limit_headers=headers
            )

        with self._lock:
            self._in_flight += 1
            if self._in_flight > self._max_concurrency:
                self._max_concurrency = self._in_flight
                self._peak_queue_length = self._in_flight

        try:
            simulated_text = self._synthesize_mock_reply(prompt)
            words = simulated_text.split()
            tokens_out = max(15, len(words) * 4 // 3)
            tokens_in = max(10, len(prompt.split()) * 4 // 3)

            ttft_ms, gen_ms = self._compute_calibrated_delay(tokens_out)
            if not self.fast_mode:
                time.sleep(min(ttft_ms / 1000.0, 1.5))

            # Stream words in chunks
            chunk_size = 4
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size]) + " "
                yield chunk
                if not self.fast_mode:
                    time.sleep(min((self.ms_per_token * chunk_size) / 1000.0, 0.1))

            return ModelResponse(
                text=simulated_text,
                first_token_ms=round(ttft_ms, 1),
                total_ms=round(ttft_ms + gen_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=tokens_in,
                estimated_output_tokens=tokens_out,
                estimated_total_tokens=tokens_in + tokens_out,
                is_simulated=True,
                provider="stand_in",
                model_name="stand-in-calibrated-v1",
                status="ok",
                rate_limit_headers=headers
            )
        finally:
            with self._lock:
                self._in_flight = max(0, self._in_flight - 1)

    def _synthesize_mock_reply(self, prompt: str) -> str:
        """Create plausible answer with citations based on prompt clues."""
        p_lower = prompt.lower()
        unanswerable_triggers = [
            "quantum", "dna private", "not mentioned", "llama-3", "patient",
            "clinical", "proprietary", "unanswerable", "d-wave", "cohort", "hospital"
        ]
        if any(w in p_lower for w in unanswerable_triggers):
            return "The provided research papers do not contain information regarding this topic."
        elif "moshi" in p_lower or "audio" in p_lower or "speech" in p_lower:
            return (
                "Moshi utilizes the Mimi neural audio codec operating at 12.5 Hz with 8 codebooks, "
                "achieving a theoretical conversational latency of 160ms. "
                "Citation: [Moshi: a speech-text foundation model for real-time dialogue, Page 4, Section 2]."
            )
        elif "dynamic chunking" in p_lower or "h-net" in p_lower:
            return (
                "Dynamic Chunking within H-Net replaces explicit tokenizers like BPE with learned byte-level "
                "hierarchies, scaling data efficiency on Chinese text and DNA sequences. "
                "Citation: [Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, Page 2, Section 1]."
            )
        elif "attention" in p_lower or "transformer" in p_lower:
            return (
                "The Transformer architecture replaces recurrence with multi-head self-attention, "
                "employing scaled dot-product attention softmax(QK^T / sqrt(d_k))V to counteract "
                "large dot products pushing softmax into small gradients. "
                "Citation: [Attention Is All You Need, Page 4, Section 3.2]."
            )
        else:
            return (
                "Based on the library analysis, the technical architecture is supported. "
                "Citation: [Attention Is All You Need, Page 3, Section 3]."
            )
