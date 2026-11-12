"""
Safe, minimal low-token live smoke test for GroqCloud API.
Can ONLY be executed if the user/owner explicitly confirms Free-tier status and authorized use.

Usage:
    python scripts/smoke_test_groq.py --confirm-free-tier --authorized
"""
import sys
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.config import GROQ_MODEL
from the_relay.models.groq_client import GroqClient

def run_smoke_test(confirm_free_tier: bool, authorized: bool):
    if not confirm_free_tier or not authorized:
        print("❌ BLOCKED: Live smoke test aborted per Safety & Account Rules.")
        print("Reason: Key owner authorization and Groq Free-tier status must both be explicitly confirmed.")
        print("Run with '--confirm-free-tier --authorized' only after owner confirmation.")
        sys.exit(1)

    print("=" * 70)
    print("GROQCLOUD MINIMAL LIVE SMOKE TEST (SAFE & ISOLATED)")
    print("=" * 70)
    print(f"Target Model:   {GROQ_MODEL}")
    print("Prompt:         'Reply with the single word: OK' (max_tokens=5)")
    print("-" * 70)

    try:
        client = GroqClient()
    except Exception as e:
        print(f"Client initialization failed: {e}")
        sys.exit(1)

    # Execute exactly ONE minimal low-token test call
    resp = client.generate(
        prompt="Reply with the single word: OK",
        max_tokens=5
    )

    print("HTTP Outcome:       ", resp.status.upper())
    print("Model ID:           ", resp.model_name)
    print("First Token (TTFT): ", f"{resp.first_token_ms} ms")
    print("Total Latency:      ", f"{resp.total_ms} ms")
    print("Tokens In / Out:    ", f"{resp.tokens_in} / {resp.tokens_out}")
    print("Request ID:         ", resp.rate_limit_headers.get("id") or resp.rate_limit_headers.get("x-request-id", "N/A"))
    
    # Redacted rate limit headers
    safe_rate_limits = {
        k: v for k, v in resp.rate_limit_headers.items()
        if k in ("retry-after", "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens", "x-ratelimit-limit-requests")
    }
    print("Rate-Limit Headers: ", safe_rate_limits)
    print("Response Content:   ", repr(resp.text))
    print("Cost:                Unknown (Do not assume $0.00 until Free-tier status is owner-verified)")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Run minimal Groq smoke test.")
    parser.add_argument(
        "--confirm-free-tier",
        action="store_true",
        help="Flag representing owner confirmation that organization is on Groq Free tier (does not technically prove billing tier)."
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Flag representing owner authorization to use this API key for project testing."
    )
    args = parser.parse_args()

    run_smoke_test(confirm_free_tier=args.confirm_free_tier, authorized=args.authorized)

if __name__ == "__main__":
    main()

