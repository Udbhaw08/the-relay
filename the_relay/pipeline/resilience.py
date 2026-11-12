"""
Resilience policies for The Relay:
- Official Groq rate-limit header parsing and state tracking.
- Truncated exponential backoff with true full jitter.
- Fine-grained transient vs permanent error classification.
- Local rolling-window request and token budget limiter with token reconciliation.
- Bounded concurrency, queue capacity, and backpressure control.
- Clear daily exhaustion notifications with dynamic reset estimation.
"""
import re
import math
import time
import random
import threading
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from collections import deque
from email.utils import parsedate_to_datetime

from the_relay.config import (
    BASE_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_RETRY_AFTER_CAP,
    LOCAL_RPM_LIMIT,
    LOCAL_TPM_LIMIT,
    LOCAL_RPD_LIMIT,
    LOCAL_TPD_LIMIT,
    MAX_CONCURRENT_REQUESTS,
    MAX_QUEUE_CAPACITY
)

@dataclass
class GroqRateLimitState:
    """Structured representation of GroqCloud rate limit headers."""
    limit_requests: Optional[int] = None
    remaining_requests: Optional[int] = None
    reset_requests_seconds: Optional[float] = None
    limit_tokens: Optional[int] = None
    remaining_tokens: Optional[int] = None
    reset_tokens_seconds: Optional[float] = None
    retry_after_seconds: Optional[float] = None
    request_id: Optional[str] = None
    raw_headers: dict[str, str] = field(default_factory=dict)

def parse_duration_string(val: Optional[str]) -> Optional[float]:
    """
    Parse duration strings returned by Groq headers into seconds.
    Supports formats like '2s', '1m30s', '500ms', '14m20s', '1h', or pure numbers '15.5'.
    """
    if not val:
        return None
    v = str(val).strip().lower()
    try:
        return float(v)
    except ValueError:
        pass

    total_seconds = 0.0
    matched = False

    # Check for hours: e.g. 1h
    h_match = re.search(r"(\d+(?:\.\d+)?)\s*h", v)
    if h_match:
        total_seconds += float(h_match.group(1)) * 3600.0
        matched = True

    # Check for minutes: e.g. 14m
    m_match = re.search(r"(\d+(?:\.\d+)?)\s*m(?!s)", v)
    if m_match:
        total_seconds += float(m_match.group(1)) * 60.0
        matched = True

    # Check for seconds: e.g. 20s
    s_match = re.search(r"(\d+(?:\.\d+)?)\s*s", v)
    if s_match:
        total_seconds += float(s_match.group(1))
        matched = True

    # Check for milliseconds: e.g. 500ms
    ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", v)
    if ms_match:
        total_seconds += float(ms_match.group(1)) / 1000.0
        matched = True

    return total_seconds if matched else None

def parse_retry_after(header_val: Optional[str], now_fn: Callable[[], float] = time.time) -> Optional[float]:
    """
    Parse a Retry-After header value into seconds.
    Handles numeric seconds ('15'), duration strings ('15s', '1m'), and HTTP-date formats.
    """
    if not header_val:
        return None
    val = str(header_val).strip()

    # Try numeric/duration parsing
    sec = parse_duration_string(val)
    if sec is not None:
        return max(0.0, sec)

    # Try HTTP date format: e.g. 'Wed, 21 Oct 2026 07:28:00 GMT'
    try:
        dt = parsedate_to_datetime(val)
        delta = (dt.timestamp() - now_fn())
        return max(0.0, delta)
    except Exception:
        return None

def extract_groq_rate_limit_state(headers: Any) -> GroqRateLimitState:
    """Extract and parse structured rate-limit metadata from Groq response headers."""
    if not headers:
        return GroqRateLimitState()

    raw: dict[str, str] = {}
    if hasattr(headers, "items"):
        for k, v in headers.items():
            raw[str(k).lower()] = str(v)
    elif isinstance(headers, dict):
        for k, v in headers.items():
            raw[str(k).lower()] = str(v)

    def _parse_int(key: str) -> Optional[int]:
        val = raw.get(key)
        if val is not None:
            try:
                return int(val)
            except ValueError:
                return None
        return None

    lim_req = _parse_int("x-ratelimit-limit-requests")
    rem_req = _parse_int("x-ratelimit-remaining-requests")
    lim_tok = _parse_int("x-ratelimit-limit-tokens")
    rem_tok = _parse_int("x-ratelimit-remaining-tokens")

    reset_req = parse_duration_string(raw.get("x-ratelimit-reset-requests"))
    reset_tok = parse_duration_string(raw.get("x-ratelimit-reset-tokens"))
    retry_after = parse_retry_after(raw.get("retry-after"))
    req_id = raw.get("x-request-id") or raw.get("id")

    return GroqRateLimitState(
        limit_requests=lim_req,
        remaining_requests=rem_req,
        reset_requests_seconds=reset_req,
        limit_tokens=lim_tok,
        remaining_tokens=rem_tok,
        reset_tokens_seconds=reset_tok,
        retry_after_seconds=retry_after,
        request_id=req_id,
        raw_headers=raw
    )

def compute_backoff(
    retry_attempt: int,
    base_seconds: float = BASE_BACKOFF_SECONDS,
    max_seconds: float = MAX_BACKOFF_SECONDS,
    retry_after_header: Optional[str] = None,
    max_retry_after_cap: float = MAX_RETRY_AFTER_CAP,
    rng: Optional[random.Random] = None
) -> float:
    """
    Truncated exponential backoff with true full jitter.
    If 'Retry-After' header is present and valid, respects it up to max_retry_after_cap.
    Otherwise applies uniform(0, min(max_backoff, base_delay * 2**attempt)).
    """
    if retry_after_header:
        ra = parse_retry_after(retry_after_header)
        if ra is not None:
            return min(max_retry_after_cap, max(0.0, ra))

    cap = min(max_seconds, base_seconds * (2 ** retry_attempt))
    r = rng if rng is not None else random
    return r.uniform(0.0, cap)

def is_retryable_error(
    status: str,
    error_message: Optional[str] = None,
    status_code: Optional[int] = None
) -> bool:
    """
    Determines whether a response error is eligible for retry.
    Retryable: Documented transient rate limits (429), timeouts (408/504), connection errors, 5xx.
    Non-retryable: Permanent client errors (400, 401, 403, 404, 422), daily budget exhaustion.
    """
    if status == "ok":
        return False

    msg = (error_message or "").lower()

    # Daily budget exhaustion is non-retryable
    if "daily budget" in msg or "daily limit" in msg or "rpd limit" in msg:
        return False

    # Permanent authentication or invalid request errors
    if status_code in (400, 401, 403, 404, 422):
        return False
    if any(k in msg for k in ["invalid api key", "unauthorized", "authentication failed", "forbidden", "not found"]):
        return False

    # Eligible transient rate limits
    if status == "rate_limited" or status_code == 429:
        return True

    # Eligible timeouts
    if status == "timeout" or status_code in (408, 504) or "timed out" in msg:
        return True

    # Eligible transient server errors
    if status_code in (500, 502, 503) or any(k in msg for k in ["internal server error", "bad gateway", "service unavailable", "connection error"]):
        return True

    return False

def format_daily_exhaustion_message(reset_seconds: Optional[float] = None) -> str:
    """
    User-facing notice when daily query budget is exhausted.
    Uses actual reset duration when available from provider headers, rather than guessing.
    """
    if reset_seconds is not None and reset_seconds > 0:
        hrs = int(reset_seconds // 3600)
        mins = int((reset_seconds % 3600) // 60)
        if hrs > 0:
            time_str = f"in approximately {hrs} hour(s) and {mins} minute(s)"
        else:
            time_str = f"in approximately {max(1, mins)} minute(s)"
    else:
        time_str = "at the provider's next daily quota reset window"

    return (
        f"⚠️ Daily Query Budget Exhausted: The system's daily LLM inference capacity has reached its limit "
        f"for today. The next quota allocation resets {time_str}. "
        f"Your request could not be processed at this time to prevent service degradation. "
        f"If your question is critical, please consult the local paper indexes or check back after the reset window."
    )

class LocalQuotaLimiter:
    """
    Thread-safe local rolling-window request and token budget limiter.
    Enforces RPM, TPM, RPD, and TPD quotas with token reservation and post-request reconciliation.
    """
    def __init__(
        self,
        rpm_limit: int = LOCAL_RPM_LIMIT,
        tpm_limit: int = LOCAL_TPM_LIMIT,
        rpd_limit: int = LOCAL_RPD_LIMIT,
        tpd_limit: int = LOCAL_TPD_LIMIT,
        clock_fn: Callable[[], float] = time.time
    ):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.rpd_limit = rpd_limit
        self.tpd_limit = tpd_limit
        self._clock_fn = clock_fn

        self._lock = threading.Lock()
        self._request_timestamps = deque()  # stores (timestamp, request_id)
        self._token_reservations = deque()  # stores (timestamp, reservation_id, tokens)
        self._daily_request_count = 0
        self._daily_token_count = 0
        self._daily_exhausted = False
        self._reservation_map: dict[str, int] = {}

    def reset(self):
        """Reset internal rate limit windows, daily counts, and reservations."""
        with self._lock:
            self._request_timestamps.clear()
            self._token_reservations.clear()
            self._reservation_map.clear()
            self._daily_request_count = 0
            self._daily_token_count = 0
            self._daily_exhausted = False

    def exhaust_daily_budget(self):
        """Force limiter into daily budget exhausted state."""
        with self._lock:
            self._daily_exhausted = True

    def halve_rpm_limit(self):
        """Halve the local RPM limit."""
        with self._lock:
            self.rpm_limit = max(1, self.rpm_limit // 2)

    def _expire_rolling_windows(self, now: float):
        """Remove entries older than 60 seconds from the rolling minute windows."""
        cutoff = now - 60.0
        while self._request_timestamps and self._request_timestamps[0][0] < cutoff:
            self._request_timestamps.popleft()

        while self._token_reservations and self._token_reservations[0][0] < cutoff:
            _, res_id, _ = self._token_reservations.popleft()
            self._reservation_map.pop(res_id, None)

    def reserve(
        self,
        estimated_tokens: int = 150,
        request_id: Optional[str] = None
    ) -> tuple[bool, Optional[str], dict[str, str]]:
        """
        Check rate limit eligibility and reserve request/token capacity.
        Returns (is_allowed, denial_reason, metadata_headers).
        """
        now = self._clock_fn()
        with self._lock:
            if self._daily_exhausted or self._daily_request_count >= self.rpd_limit:
                return False, "daily_budget_exhausted", {
                    "error": "Daily request budget exhausted",
                    "retry-after": "43200",
                    "x-ratelimit-remaining-requests": "0"
                }

            if self._daily_token_count + estimated_tokens > self.tpd_limit:
                return False, "daily_budget_exhausted", {
                    "error": "Daily token budget exhausted",
                    "retry-after": "43200",
                    "x-ratelimit-remaining-tokens": "0"
                }

            self._expire_rolling_windows(now)

            # Check RPM
            if len(self._request_timestamps) >= self.rpm_limit:
                oldest_ts = self._request_timestamps[0][0]
                retry_wait = max(1, math.ceil(60.0 - (now - oldest_ts)))
                return False, "rpm_limit_exceeded", {
                    "error": f"Local RPM limit exceeded ({self.rpm_limit} RPM)",
                    "retry-after": str(retry_wait),
                    "x-ratelimit-remaining-requests": "0"
                }

            # Check TPM
            current_minute_tokens = sum(t for _, _, t in self._token_reservations)
            if current_minute_tokens + estimated_tokens > self.tpm_limit:
                oldest_token_ts = self._token_reservations[0][0] if self._token_reservations else now
                retry_wait = max(1, math.ceil(60.0 - (now - oldest_token_ts)))
                return False, "tpm_limit_exceeded", {
                    "error": f"Local TPM limit exceeded ({self.tpm_limit} TPM)",
                    "retry-after": str(retry_wait),
                    "x-ratelimit-remaining-tokens": "0"
                }

            # Reserve capacity
            eff_req_id = request_id or f"req_{int(now * 1000)}"
            res_id = f"res_{eff_req_id}"
            self._request_timestamps.append((now, eff_req_id))
            self._token_reservations.append((now, res_id, estimated_tokens))
            self._reservation_map[res_id] = estimated_tokens
            self._daily_request_count += 1
            self._daily_token_count += estimated_tokens

            rem_req = max(0, self.rpm_limit - len(self._request_timestamps))
            rem_tok = max(0, self.tpm_limit - (current_minute_tokens + estimated_tokens))

            return True, None, {
                "x-ratelimit-remaining-requests": str(rem_req),
                "x-ratelimit-remaining-tokens": str(rem_tok),
                "reservation_id": res_id
            }

    def reconcile(self, reservation_id: str, actual_tokens: int):
        """
        Reconcile estimated token reservation with actual provider token consumption.
        Adjusts rolling minute and daily counters based on the delta.
        """
        with self._lock:
            est_tokens = self._reservation_map.get(reservation_id)
            if est_tokens is None:
                return

            delta = actual_tokens - est_tokens
            self._reservation_map[reservation_id] = actual_tokens

            # Update entry in deque
            for i, (ts, r_id, tok) in enumerate(self._token_reservations):
                if r_id == reservation_id:
                    self._token_reservations[i] = (ts, r_id, actual_tokens)
                    break

            # Adjust daily count
            self._daily_token_count = max(0, self._daily_token_count + delta)

class BackpressureController:
    """
    Manages bounded concurrency and queued request backlog.
    Rejects requests with explicit backpressure when the queue capacity is breached.
    """
    def __init__(
        self,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
        max_queue_depth: int = MAX_QUEUE_CAPACITY
    ):
        self.max_concurrency = max_concurrency
        self.max_queue_depth = max_queue_depth
        self._lock = threading.Lock()
        self._in_flight = 0
        self._queued = 0

    def admit_request(self) -> tuple[bool, Optional[str]]:
        """
        Attempt to admit a request into the system.
        Returns (admitted, rejection_reason).
        """
        with self._lock:
            if self._queued >= self.max_queue_depth:
                return False, "queue_capacity_breached_backpressure"
            self._queued += 1
            return True, None

    def begin_execution(self):
        """Move request from queue backlog into active in-flight execution."""
        with self._lock:
            self._queued = max(0, self._queued - 1)
            self._in_flight += 1

    def finish_execution(self):
        """Release execution slot upon completion."""
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "in_flight": self._in_flight,
                "queued": self._queued,
                "max_concurrency": self.max_concurrency,
                "max_queue_depth": self.max_queue_depth
            }
