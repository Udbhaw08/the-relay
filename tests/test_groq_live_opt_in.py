"""Opt-in live integration test for GroqCloud API.

STRICT SAFETY POLICY:
This test is strictly skipped by default during normal pytest runs and CI.
It will ONLY run if all of the following environment variables are explicitly provided:
- RUN_LIVE_GROQ_TEST=1
- CONFIRM_FREE_TIER=1
- AUTHORIZED=1
- GROQ_API_KEY is non-empty and valid

Under normal conditions, this test is skipped to prevent consuming unverified API quota.
"""
import os
import pytest
from the_relay.models.groq_client import GroqClient
from the_relay.config import GROQ_MODEL

@pytest.mark.skipif(
    not (
        os.getenv("RUN_LIVE_GROQ_TEST") == "1"
        and os.getenv("CONFIRM_FREE_TIER") == "1"
        and os.getenv("AUTHORIZED") == "1"
    ),
    reason="Live Groq test is opt-in only. Standard test suite must run offline without consuming live Groq quota."
)
def test_opt_in_live_groq_single_minimal_call():
    """Execute a single minimal 5-token call to verify live GroqCloud connectivity when authorized."""
    api_key = os.getenv("GROQ_API_KEY")
    assert api_key and api_key.strip(), "GROQ_API_KEY must be provided for live test"

    client = GroqClient(api_key=api_key, model_name=GROQ_MODEL)
    response = client.generate("Say 'Relay OK' and nothing else.", max_tokens=5)

    assert response.status == "ok"
    assert response.provider == "groq"
    assert not response.is_simulated
    assert response.tokens_out > 0
    assert response.first_token_ms is not None
    assert response.first_token_ms > 0
