"""Unit tests for the Calibrated Stand-In Model."""
from the_relay.models.stand_in import StandInModelClient

def test_stand_in_basic_generation():
    client = StandInModelClient(rpm_limit=100, timeout_rate=0.0, failure_rate=0.0, fast_mode=True)
    resp = client.generate("What is the Mimi neural audio codec?")
    assert resp.status == "ok"
    assert "Moshi" in resp.text
    assert resp.first_token_ms > 0
    assert resp.total_ms >= resp.first_token_ms

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
    assert "Daily budget" in resp.error_message
    assert resp.rate_limit_headers.get("x-ratelimit-limit-requests") == str(client.rpd_limit)
    assert resp.rate_limit_headers.get("x-ratelimit-remaining-requests") == "0"

