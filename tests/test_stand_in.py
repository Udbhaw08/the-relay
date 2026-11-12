"""Unit tests for the Calibrated Stand-In Model."""
from the_relay.models.stand_in import StandInModelClient

def test_stand_in_basic_generation():
    client = StandInModelClient(rpm_limit=100, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    resp = client.generate("What is the Mimi neural audio codec?")
    assert resp.status == "ok"
    assert "Moshi" in resp.text
    assert resp.first_token_ms > 0
    assert resp.total_ms >= resp.first_token_ms
    assert resp.is_simulated is True
    assert resp.provider == "stand_in"

def test_stand_in_rate_limiting():
    # Set limit to 2 RPM with zero random faults for deterministic rate limit testing
    client = StandInModelClient(rpm_limit=2, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    resp1 = client.generate("Question 1")
    resp2 = client.generate("Question 2")
    resp3 = client.generate("Question 3")  # Should breach 2 RPM
    assert resp1.status == "ok"
    assert resp2.status == "ok"
    assert resp3.status == "rate_limited"
    assert "retry-after" in resp3.rate_limit_headers

def test_stand_in_daily_budget_exhaustion():
    client = StandInModelClient(timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    client.exhaust_daily_budget()
    resp = client.generate("Question after 3pm")
    assert resp.status == "rate_limited"
    assert "daily" in resp.error_message.lower() and "budget" in resp.error_message.lower()
    assert resp.rate_limit_headers.get("x-ratelimit-limit-requests") == str(client.rpd_limit)
    assert resp.rate_limit_headers.get("x-ratelimit-remaining-requests") == "0"

def test_stand_in_tpm_tracked_token_consumption_rejection():
    # Set TPM limit to 100 tokens without setting _tpm_exhausted flag
    client = StandInModelClient(rpm_limit=100, tpm_limit=100, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    assert client._tpm_exhausted is False

    # 1st request consumes tokens
    resp1 = client.generate("Short prompt")
    assert resp1.status == "ok"
    assert resp1.is_simulated is True

    # 2nd request with prompt exceeding remaining TPM capacity triggers rejection via tracked token consumption!
    long_prompt = "What is " + "attention " * 80
    resp2 = client.generate(long_prompt)
    assert resp2.status == "rate_limited"
    assert "Token limit exceeded" in resp2.error_message
    assert resp2.rate_limit_headers.get("x-ratelimit-remaining-tokens") == "0"
    assert resp2.is_simulated is True

def test_stand_in_tpd_tracked_daily_token_consumption_rejection():
    # Set TPD limit to 150 tokens without setting manual boolean flags
    client = StandInModelClient(rpm_limit=100, tpm_limit=100000, tpd_limit=150, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    assert client._daily_budget_exhausted is False

    resp1 = client.generate("Query one")
    assert resp1.status == "ok"

    # Next request breaches daily token limit
    long_prompt = "Explain " + "transformer " * 120
    resp2 = client.generate(long_prompt)
    assert resp2.status == "rate_limited"
    assert "Daily token budget exhausted" in resp2.error_message
    assert resp2.rate_limit_headers.get("x-ratelimit-remaining-tokens") == "0"

def test_stand_in_isolated_context_restores_limits():
    client = StandInModelClient(rpm_limit=15, tpm_limit=50000)
    assert client.rpm_limit == 15

    with client.isolated_context(rpm_limit=1000, tpm_limit=999999):
        assert client.rpm_limit == 1000
        assert client.tpm_limit == 999999

    # Strictly restored upon exit
    assert client.rpm_limit == 15
    assert client.tpm_limit == 50000
