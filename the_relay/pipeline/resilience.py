"""
Resilience policies: Exponential backoff with jitter, budget exhaustion handler,
and rate-limit mitigation strategies.
"""
import random
import time
from typing import Optional

def compute_backoff(retry_attempt: int, base_seconds: float = 2.0, max_seconds: float = 30.0, retry_after_header: Optional[str] = None) -> float:
    """
    Truncated exponential backoff with full jitter.
    Respects upstream 'retry-after' header if provided.
    """
    if retry_after_header:
        try:
            return float(retry_after_header)
        except ValueError:
            pass

    raw_backoff = min(max_seconds, base_seconds * (2 ** retry_attempt))
    # Full jitter: random between 0.5 * raw and raw
    return random.uniform(0.5 * raw_backoff, raw_backoff)

def format_daily_exhaustion_message() -> str:
    """
    User-facing message returned when daily budget is exhausted (Addresses brief heading 7).
    """
    return (
        "⚠️ Daily Query Budget Exhausted: The system's daily LLM inference capacity has reached its limit "
        "for today. The next quota allocation resets at 00:00 UTC (in approximately 9 hours). "
        "Your request could not be processed at this time to prevent service degradation. "
        "If your question is critical, please consult the local paper indexes or check back after the reset window."
    )

def is_retryable_error(status: str, error_message: Optional[str]) -> bool:
    """
    Determines if an error should trigger a retry.
    Note on failure case: Non-retryable errors (e.g. invalid context, malformed syntax,
    or daily quota exhaustion) MUST NOT be retried, as retrying them exacerbates rate limits
    and thundering herd lockups.
    """
    if status == "ok":
        return False
    if "daily budget" in (error_message or "").lower():
        return False  # Daily limit cannot be fixed by immediate retries
    if status in ("rate_limited", "timeout"):
        return True
    return False

