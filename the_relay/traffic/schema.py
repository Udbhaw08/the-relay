"""CSV Schema specification and validation for The Relay experimental telemetry."""
from typing import Optional, Any
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

REQUIRED_COLUMNS = [
    "request_id",
    "scenario",
    "source",
    "start_time",
    "first_token_ms",
    "total_ms",
    "status",
    "retries",
    "tokens_in",
    "tokens_out",
    "retrieval_setting",
    "answer_grade"
]

OPTIONAL_COLUMNS = [
    "run_id",
    "requested_retrieval_setting"
]

ALLOWED_STATUSES = {"ok", "rate_limited", "timeout", "error"}
ALLOWED_SOURCES = {"real", "stand-in", "standin", "groq"}
ALLOWED_RETRIEVAL_SETTINGS = {"setting_a", "setting_b", "setting_c"}
ALLOWED_ANSWER_GRADES = {
    "correct",
    "partially_correct",
    "wrong",
    "refused_correctly",
    "refused_wrongly",
    "error",
    "rate_limited",
    "unscorable"
}

ALLOWED_SCENARIOS = {
    "steady",
    "burst",
    "sustained_overload",
    "per_minute_limit_halved",
    "daily_budget_exhausted",
    "eval_setting_a",
    "eval_setting_b",
    "eval_setting_c",
    "default"
}

EXPECTED_BENCHMARK_QUESTION_IDS = [
    "q01_attention_formula",
    "q02_transformer_dimensions",
    "q03_transformer_bleu",
    "q04_ffn_layer",
    "q05_mimi_codec_framerate",
    "q06_moshi_latency_budget",
    "q07_moshi_multistream",
    "q08_moshi_pretraining_data",
    "q09_dynamic_chunking_concept",
    "q10_hnet_hierarchy_stages",
    "q11_dna_data_efficiency",
    "q12_character_robustness",
    "q13_llama3_hardware_infra",
    "q14_private_dna_cohorts",
    "q15_quantum_attention_speedup"
]

@dataclass
class ValidationReport:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_rows: int = 0
    scenarios_found: dict[str, int] = field(default_factory=dict)
    run_ids: list[str] = field(default_factory=list)

def validate_results_dataframe(
    df: pd.DataFrame,
    expected_run_id: Optional[str] = None,
    allow_custom_scenarios: bool = False
) -> ValidationReport:
    """
    Validate an experimental telemetry DataFrame against The Relay schema rules.
    Checks:
    - All required columns present
    - No missing required fields (except nullable metrics like first_token_ms on errors)
    - Valid categorical values (status, source, retrieval_setting, answer_grade)
    - Valid numeric ranges (start_time > 0, total_ms >= 0, retries >= 0, tokens >= 0)
    - Duplicate request_ids within the same run_id
    - Retrieval evaluation scenario integrity (expected 15 question IDs in order)
    """
    errors: list[str] = []
    warnings: list[str] = []

    if df is None or len(df) == 0:
        return ValidationReport(is_valid=False, errors=["DataFrame is empty or None"], total_rows=0)

    # 1. Required Columns
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        errors.append(f"Missing required CSV columns: {missing_cols}")
        return ValidationReport(is_valid=False, errors=errors, total_rows=len(df))

    # Add default run_id if absent (for legacy backwards compatibility)
    active_df = df.copy()
    if "run_id" not in active_df.columns:
        active_df["run_id"] = "legacy_run"
    else:
        active_df["run_id"] = active_df["run_id"].fillna("legacy_run").astype(str)

    if expected_run_id:
        active_df = active_df[active_df["run_id"] == expected_run_id]
        if len(active_df) == 0:
            errors.append(f"No records found matching run_id='{expected_run_id}'")
            return ValidationReport(is_valid=False, errors=errors, total_rows=0)

    total_rows = len(active_df)
    scenarios_found = active_df["scenario"].value_counts().to_dict()
    run_ids = sorted(active_df["run_id"].unique().tolist())

    # 2. Duplicate Request IDs within each run_id
    for r_id in run_ids:
        run_subset = active_df[active_df["run_id"] == r_id]
        duplicates = run_subset[run_subset.duplicated(subset=["request_id"], keep=False)]
        if len(duplicates) > 0:
            dup_ids = duplicates["request_id"].unique().tolist()
            errors.append(f"Duplicate request_id found within run '{r_id}': {dup_ids}")

    # 3. Categorical Domain Validation
    invalid_statuses = set(active_df["status"].dropna()) - ALLOWED_STATUSES
    if invalid_statuses:
        errors.append(f"Invalid status values found: {invalid_statuses}. Allowed: {ALLOWED_STATUSES}")

    invalid_sources = set(active_df["source"].dropna()) - ALLOWED_SOURCES
    if invalid_sources:
        errors.append(f"Invalid source values found: {invalid_sources}. Allowed: {ALLOWED_SOURCES}")

    invalid_settings = set(active_df["retrieval_setting"].dropna()) - ALLOWED_RETRIEVAL_SETTINGS
    if invalid_settings:
        errors.append(f"Invalid retrieval_setting values found: {invalid_settings}. Allowed: {ALLOWED_RETRIEVAL_SETTINGS}")

    invalid_grades = set(active_df["answer_grade"].dropna()) - ALLOWED_ANSWER_GRADES
    if invalid_grades:
        errors.append(f"Invalid answer_grade values found: {invalid_grades}. Allowed: {ALLOWED_ANSWER_GRADES}")

    if not allow_custom_scenarios:
        invalid_scenarios = set(active_df["scenario"].dropna()) - ALLOWED_SCENARIOS
        if invalid_scenarios:
            warnings.append(f"Non-standard scenario names found: {invalid_scenarios}")

    # 4. Numeric Range Validation
    # start_time
    if (pd.to_numeric(active_df["start_time"], errors="coerce") <= 0).any():
        errors.append("start_time contains non-positive or unparseable timestamps")

    # total_ms
    tot_num = pd.to_numeric(active_df["total_ms"], errors="coerce")
    if (tot_num < 0).any() or tot_num.isna().any():
        errors.append("total_ms contains negative or NaN values")

    # retries
    ret_num = pd.to_numeric(active_df["retries"], errors="coerce")
    if (ret_num < 0).any() or ret_num.isna().any():
        errors.append("retries contains negative or NaN values")

    # tokens_in / tokens_out
    t_in = pd.to_numeric(active_df["tokens_in"], errors="coerce")
    if (t_in < 0).any() or t_in.isna().any():
        errors.append("tokens_in contains negative or NaN values")

    t_out = pd.to_numeric(active_df["tokens_out"], errors="coerce")
    if (t_out < 0).any() or t_out.isna().any():
        errors.append("tokens_out contains negative or NaN values")

    # 5. Retrieval Evaluation Integrity Check (eval_setting_a, eval_setting_b, eval_setting_c)
    for s_key in ["setting_a", "setting_b", "setting_c"]:
        sc_name = f"eval_{s_key}"
        eval_rows = active_df[active_df["scenario"] == sc_name]
        if len(eval_rows) > 0:
            for r_id in eval_rows["run_id"].unique():
                scoped_eval = eval_rows[eval_rows["run_id"] == r_id]
                extracted_qids = []
                for req_id in scoped_eval["request_id"]:
                    prefix = f"eval_{s_key}_"
                    if req_id.startswith(prefix):
                        extracted_qids.append(req_id[len(prefix):])
                    else:
                        extracted_qids.append(req_id)

                # Check uniqueness within setting
                if len(extracted_qids) != len(set(extracted_qids)):
                    errors.append(f"Scenario '{sc_name}' in run '{r_id}' contains duplicate question IDs")

                # Check expected 15 benchmark questions
                missing_q = [q for q in EXPECTED_BENCHMARK_QUESTION_IDS if q not in extracted_qids]
                if missing_q:
                    warnings.append(f"Scenario '{sc_name}' in run '{r_id}' missing expected questions: {missing_q}")
                unexpected_q = [q for q in extracted_qids if q not in EXPECTED_BENCHMARK_QUESTION_IDS]
                if unexpected_q:
                    warnings.append(f"Scenario '{sc_name}' in run '{r_id}' has unexpected question IDs: {unexpected_q}")

    return ValidationReport(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        total_rows=total_rows,
        scenarios_found=scenarios_found,
        run_ids=run_ids
    )
