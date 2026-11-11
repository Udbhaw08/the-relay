"""Unit tests for the Calibrated Stand-In Model."""
from the_relay.models.stand_in import StandInModelClient

def test_stand_in_basic_generation():
    client = StandInModelClient(rpm_limit=100)
    resp = client.generate("What is the Mimi neural audio codec?")
    assert resp.status == "ok"
    assert "Moshi" in resp.text
    assert resp.first_token_ms > 0
    assert resp.total_ms >= resp.first_token_ms

def test_stand_in_rate_limiting():
    # Set limit to 2 RPM
    client = StandInModelClient(rpm_limit=2)
    resp1 = client.generate("Question 1")
    resp2 = client.generate("Question 2")
    resp3 = client.generate("Question 3")  # Should breach 2 RPM
    assert resp1.status == "ok"
    assert resp2.status == "ok"
    assert resp3.status == "rate_limited"
    assert "retry-after" in resp3.rate_limit_headers

def test_stand_in_daily_budget_exhaustion():
    client = StandInModelClient()
    client.exhaust_daily_budget()
    resp = client.generate("Question after 3pm")
    assert resp.status == "rate_limited"
    assert "Daily budget" in resp.error_message

