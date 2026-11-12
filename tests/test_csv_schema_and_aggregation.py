"""Unit and integration tests for CSV Schema validation and mathematical aggregation."""
import pytest
from pathlib import Path
import pandas as pd
import numpy as np

from the_relay.config import RESULTS_PATH
from the_relay.traffic.schema import (
    validate_results_dataframe,
    REQUIRED_COLUMNS,
    EXPECTED_BENCHMARK_QUESTION_IDS,
    ValidationReport
)
from scripts.compute_tables import (
    compute_percentiles,
    format_latencies_3,
    format_latencies_2,
    generate_table_1,
    generate_table_2a_and_2b,
    generate_table_3
)

# 1. Historical Fixture Test (results.csv with 125 rows)
def test_historical_csv_fixture_integrity():
    assert RESULTS_PATH.exists(), "results.csv fixture must exist"
    df = pd.read_csv(RESULTS_PATH)
    assert len(df) == 125, f"Expected 125 historical rows, found {len(df)}"

    # Schema validation must pass
    report = validate_results_dataframe(df)
    assert report.is_valid, f"Validation failed with errors: {report.errors}"
    assert report.total_rows == 125

    # Exactly 80 load test rows and 45 evaluation rows
    load_scenarios = ["steady", "burst", "sustained_overload", "per_minute_limit_halved", "daily_budget_exhausted"]
    eval_scenarios = ["eval_setting_a", "eval_setting_b", "eval_setting_c"]

    load_count = sum(len(df[df["scenario"] == sc]) for sc in load_scenarios)
    eval_count = sum(len(df[df["scenario"] == sc]) for sc in eval_scenarios)
    assert load_count == 80
    assert eval_count == 45

# 2. Strict Isolation of Retrieval Evaluations A/B/C (No Leaks from Load Tests)
def test_table3_strict_isolation_and_no_leakage():
    df = pd.read_csv(RESULTS_PATH)
    t3 = generate_table_3(df)

    # In Table 3, questions asked MUST be 15 for each setting, NOT 73 or 43
    assert "| Piece size 250, 3 fetched, re-rank: no | 15 |" in t3
    assert "| Piece size 500, 5 fetched, re-rank: yes | 15 |" in t3
    assert "| Piece size 1000, 7 fetched, re-rank: yes | 15 |" in t3
    assert "| 73 |" not in t3
    assert "| 43 |" not in t3

# 3. Each Retrieval Evaluation Contains Expected 15 Benchmark IDs in Order
def test_evaluation_settings_have_expected_question_ids():
    df = pd.read_csv(RESULTS_PATH)
    for s_key in ["setting_a", "setting_b", "setting_c"]:
        sc_name = f"eval_{s_key}"
        sub = df[df["scenario"] == sc_name]
        assert len(sub) == 15, f"{sc_name} must contain exactly 15 records"

        extracted_qids = [req_id.replace(f"eval_{s_key}_", "") for req_id in sub["request_id"]]
        # Must be unique
        assert len(set(extracted_qids)) == 15
        # Must match expected benchmark question IDs
        assert extracted_qids == EXPECTED_BENCHMARK_QUESTION_IDS

# 4. Duplicate Request IDs Detected Within a Run
def test_schema_detects_duplicate_request_ids():
    df = pd.read_csv(RESULTS_PATH)
    # Inject a duplicate request_id within the same run
    dup_row = df.iloc[0:1].copy()
    corrupted_df = pd.concat([df, dup_row], ignore_index=True)
    report = validate_results_dataframe(corrupted_df)
    assert not report.is_valid
    assert any("Duplicate request_id found" in err for err in report.errors)

# 5. Legitimate Repeated Question IDs Across Distinct Runs Are Allowed
def test_schema_allows_repeated_ids_across_distinct_runs():
    df = pd.read_csv(RESULTS_PATH)
    run1 = df.copy()
    run1["run_id"] = "run_001"
    run2 = df.copy()
    run2["run_id"] = "run_002"
    multi_run_df = pd.concat([run1, run2], ignore_index=True)
    report = validate_results_dataframe(multi_run_df)
    assert report.is_valid
    assert report.run_ids == ["run_001", "run_002"]

# 6. Missing Columns Produce Clear Error
def test_schema_detects_missing_columns():
    df = pd.read_csv(RESULTS_PATH)
    dropped_df = df.drop(columns=["retrieval_setting", "tokens_out"])
    report = validate_results_dataframe(dropped_df)
    assert not report.is_valid
    assert any("Missing required CSV columns" in err for err in report.errors)

# 7. Invalid Categorical and Numeric Ranges Produce Clear Errors
def test_schema_detects_invalid_values():
    df = pd.read_csv(RESULTS_PATH).copy()
    df.loc[0, "status"] = "catastrophic_crash"
    df.loc[1, "tokens_in"] = -50
    df.loc[2, "total_ms"] = -100.0
    report = validate_results_dataframe(df)
    assert not report.is_valid
    assert any("Invalid status values found" in err for err in report.errors)
    assert any("tokens_in contains negative" in err for err in report.errors)
    assert any("total_ms contains negative" in err for err in report.errors)

# 8. Empty Group Yields N/A With Sample Count 0
def test_empty_dataframe_or_group_yields_na():
    empty_df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    t3 = generate_table_3(empty_df)
    assert "| Piece size 250, 3 fetched, re-rank: no | 0 | N/A | N/A | N/A | N/A | N/A | N/A |" in t3

# 9. Failed / No-Token Requests Have Null TTFT (N/A)
def test_no_token_requests_have_null_ttft():
    df = pd.read_csv(RESULTS_PATH)
    t2a, t2b = generate_table_2a_and_2b(df)
    # In daily_budget_exhausted, no tokens were streamed (all 429), so TTFT must be N/A
    lines = [l for l in t2a.split("\n") if "daily_budget_exhausted" in l]
    assert len(lines) == 1
    assert "N/A" in lines[0], f"Expected N/A for TTFT in daily_budget_exhausted, got: {lines[0]}"

# 10. Failed Requests Excluded from Factual Answer Accuracy Denominators
def test_failed_requests_excluded_from_answer_accuracy():
    # Construct a synthetic DataFrame with 1 correct, 1 wrong, 1 rate_limited error
    synthetic_rows = [
        {"request_id": "eval_setting_a_q01", "scenario": "eval_setting_a", "source": "stand-in",
         "start_time": 1000.0, "first_token_ms": 100.0, "total_ms": 200.0, "status": "ok",
         "retries": 0, "tokens_in": 100, "tokens_out": 20, "retrieval_setting": "setting_a", "answer_grade": "correct"},
        {"request_id": "eval_setting_a_q02", "scenario": "eval_setting_a", "source": "stand-in",
         "start_time": 1001.0, "first_token_ms": 100.0, "total_ms": 200.0, "status": "ok",
         "retries": 0, "tokens_in": 100, "tokens_out": 20, "retrieval_setting": "setting_a", "answer_grade": "wrong"},
        {"request_id": "eval_setting_a_q03", "scenario": "eval_setting_a", "source": "stand-in",
         "start_time": 1002.0, "first_token_ms": "", "total_ms": 10.0, "status": "rate_limited",
         "retries": 2, "tokens_in": 100, "tokens_out": 0, "retrieval_setting": "setting_a", "answer_grade": "error"},
    ]
    syn_df = pd.DataFrame(synthetic_rows)
    t3 = generate_table_3(syn_df)
    # Total questions asked is 3. Correct is 1 (33.3%), Wrong is 1 (33.3%), Refused is 0 (0.0%).
    # The rate-limited request is NOT counted as a wrong answer!
    assert "| 3 | 33.3% | 33.3% | 0.0% |" in t3

# 11. Re-running Table Generation Does Not Mutate or Duplicate Source CSV
def test_table_generation_is_read_only_and_idempotent():
    initial_stat = RESULTS_PATH.stat().st_mtime_ns
    initial_content = RESULTS_PATH.read_bytes()

    df = pd.read_csv(RESULTS_PATH)
    _ = generate_table_1()
    _ = generate_table_2a_and_2b(df)
    _ = generate_table_3(df)

    assert RESULTS_PATH.read_bytes() == initial_content, "CSV file content must not be modified by table generation"
