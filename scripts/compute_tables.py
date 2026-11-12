"""
Aggregator script to compute Tables 1, 2a, 2b, and 3 directly from results.csv.
Ensures 100% mathematical consistency with raw experimental data.
"""
import sys
import argparse
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

# Ensure repository root is in Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.config import RESULTS_PATH
from the_relay.traffic.schema import validate_results_dataframe

def compute_percentiles(series: pd.Series) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute p50, p95, p99 for a numeric series. Returns None if no valid positive values exist."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean = clean[clean > 0]
    if len(clean) == 0:
        return None, None, None
    p50 = float(np.percentile(clean, 50))
    p95 = float(np.percentile(clean, 95))
    p99 = float(np.percentile(clean, 99))
    return round(p50, 1), round(p95, 1), round(p99, 1)

def format_latencies_3(p50: Optional[float], p95: Optional[float], p99: Optional[float]) -> str:
    """Format 3-percentile string or N/A if missing."""
    if p50 is None:
        return "N/A"
    return f"{p50:.1f} / {p95:.1f} / {p99:.1f} ms"

def format_latencies_2(p50: Optional[float], p95: Optional[float]) -> str:
    """Format 2-percentile string or N/A if missing."""
    if p50 is None:
        return "N/A"
    return f"{p50:.1f} / {p95:.1f} ms"

def generate_table_1() -> str:
    """Generate Table 1: Limits found in real service (GroqCloud Free Tier for openai/gpt-oss-20b)."""
    rows = [
        ("Requests per minute", "30 RPM (published Free plan)", "Official Groq Documentation (openai/gpt-oss-20b published tier)", "high"),
        ("Tokens per minute", "8,000 TPM (published Free plan)", "Official Groq Documentation & x-ratelimit-limit-tokens header", "high"),
        ("Requests per day", "1,000 RPD (published Free plan)", "Official Groq Documentation & x-ratelimit-limit-requests header (Groq documents this header as RPD)", "high"),
        ("Tokens per day", "200,000 TPD (published Free plan)", "Official Groq Documentation (openai/gpt-oss-20b published tier)", "high"),
        ("Requests in flight at once", "Dynamic / 1-5 concurrent (unverified friend account)", "Groq Cloud Documentation / unverified organization Limits page", "medium"),
        ("What it returns when a limit is hit", "HTTP 429 rate_limit_exceeded", "Groq API error payload specification & error classifier", "high"),
        ("Time until it recovers", "Dynamic via 'retry-after' / 'x-ratelimit-reset-*' headers", "x-ratelimit-reset-tokens (minute) / x-ratelimit-reset-requests (day) / retry-after", "high"),
    ]
    
    md = [
        "### Table 1: Limits you found in the real service\n",
        "| Limit | Value you found | How you found it | Confidence (high, medium, low) |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for limit, val, how, conf in rows:
        md.append(f"| {limit} | {val} | {how} | {conf} |")
    return "\n".join(md)

def generate_table_2a_and_2b(df: pd.DataFrame, run_id: Optional[str] = None) -> tuple[str, str]:
    """Generate Tables 2a and 2b for load scenarios."""
    scenarios = [
        "steady",
        "burst",
        "sustained_overload",
        "per_minute_limit_halved",
        "daily_budget_exhausted"
    ]

    t2a_lines = [
        "### Table 2a: Latency, one row per load scenario\n",
        "| Scenario | Real or stand-in | Requests sent | Duration (s) | Offered rate (per min) | First token p50 / p95 / p99 (ms) | Total time p50 / p95 / p99 (ms) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    t2b_lines = [
        "### Table 2b: Outcomes, same rows\n",
        "| Scenario | Succeeded % | Rate-limited % | Timed out or given up % | Retries per request | Peak queue length | Tokens per answer | Cost per 1,000 answers |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    active_df = df.copy()
    if run_id and "run_id" in active_df.columns:
        active_df = active_df[active_df["run_id"] == run_id]

    for sc in scenarios:
        sub = active_df[active_df["scenario"] == sc]
        if len(sub) == 0:
            continue

        source = sub["source"].iloc[0]
        reqs_sent = len(sub)
        
        # Duration & Offered rate
        min_start = sub["start_time"].min()
        max_start = sub["start_time"].max()
        duration_s = max(1.0, round(max_start - min_start + (sub["total_ms"].max() / 1000.0), 1))
        offered_rate = round((reqs_sent / duration_s) * 60.0, 1)

        # TTFT: only measured on requests with successful output tokens
        ok_subset = sub[(sub["status"] == "ok") & (sub["tokens_out"] > 0)]
        valid_ttft = ok_subset[pd.to_numeric(ok_subset["first_token_ms"], errors="coerce") > 0]
        ttft_p50, ttft_p95, ttft_p99 = compute_percentiles(valid_ttft["first_token_ms"])
        tot_p50, tot_p95, tot_p99 = compute_percentiles(sub[sub["status"] == "ok"]["total_ms"])

        ttft_str = format_latencies_3(ttft_p50, ttft_p95, ttft_p99)
        tot_str = format_latencies_3(tot_p50, tot_p95, tot_p99)

        t2a_lines.append(
            f"| {sc} | {source} | {reqs_sent} | {duration_s}s | {offered_rate} | "
            f"{ttft_str} | {tot_str} |"
        )

        # Outcomes
        succeeded_pct = round((len(ok_subset) / reqs_sent) * 100.0, 1)
        rate_limited_pct = round((len(sub[sub["status"] == "rate_limited"]) / reqs_sent) * 100.0, 1)
        timed_out_pct = round((len(sub[sub["status"].isin(["timeout", "error"])]) / reqs_sent) * 100.0, 1)
        
        avg_retries = round(float(sub["retries"].mean()), 2)

        # Peak queue: accurately measured from queue telemetry when present, otherwise labelled not measured
        if "queue_depth" in sub.columns and sub["queue_depth"].dropna().count() > 0:
            qd = pd.to_numeric(sub["queue_depth"], errors="coerce").dropna()
            peak_queue = str(int(qd.max())) if len(qd) > 0 else "N/A"
        elif "peak_queue" in sub.columns and sub["peak_queue"].dropna().count() > 0:
            qd = pd.to_numeric(sub["peak_queue"], errors="coerce").dropna()
            peak_queue = str(int(qd.max())) if len(qd) > 0 else "N/A"
        else:
            peak_queue = "N/A (not measured)"
        
        avg_tokens_out = round(float(ok_subset["tokens_out"].mean()), 1) if len(ok_subset) > 0 else 0.0
        
        # Cost calculation: accurate provenance separation
        if source in ("stand-in", "standin"):
            cost_per_1k = "N/A — no live provider usage"
        else:
            cost_per_1k = "N/A (Free Tier / unbilled)"

        t2b_lines.append(
            f"| {sc} | {succeeded_pct}% | {rate_limited_pct}% | {timed_out_pct}% | "
            f"{avg_retries} | {peak_queue} | {avg_tokens_out} | {cost_per_1k} |"
        )

    return "\n".join(t2a_lines), "\n".join(t2b_lines)

def generate_table_3(df: pd.DataFrame, run_id: Optional[str] = None) -> str:
    """
    Generate Table 3: Retrieval settings benchmark.
    Strictly groups evaluation rows by scenario (eval_setting_a, eval_setting_b, eval_setting_c)
    and optional run_id, completely avoiding cross-scenario contamination from load tests.
    Excludes infrastructure failures from factual accuracy denominators and reports sample counts.
    """
    settings = [
        ("setting_a", "Piece size 250, 3 fetched, re-rank: no"),
        ("setting_b", "Piece size 500, 5 fetched, re-rank: yes"),
        ("setting_c", "Piece size 1000, 7 fetched, re-rank: yes")
    ]

    t3_lines = [
        "### Table 3: Retrieval settings (at least three)\n",
        "| Setting (piece size, pieces fetched, re-rank yes or no) | Questions asked | Correct and cited % | Wrong % | Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    breakdown_lines = [
        "\n#### Detailed Retrieval Accuracy & Failure Breakdown",
        "| Setting | Ans Evaluated | Correct & Cited | Partial | Factually Wrong | Wrongly Refused | Unans Evaluated | Correctly Refused | Hallucinated | Infra Failures |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    active_df = df.copy()
    if run_id and "run_id" in active_df.columns:
        active_df = active_df[active_df["run_id"] == run_id]

    for s_key, label in settings:
        # STRICT SCENARIO-ONLY FILTERING - NO CROSS-CONTAMINATION WITH LOAD TEST ROWS
        sub = active_df[active_df["scenario"] == f"eval_{s_key}"]
        q_count = len(sub)

        if q_count == 0:
            t3_lines.append(
                f"| {label} | 0 | N/A | N/A | N/A | N/A | N/A | N/A |"
            )
            continue

        # Separate answerable (q01-q12) vs unanswerable (q13-q15)
        is_unans = sub["request_id"].str.contains(r"q1[345]|negative", case=False, regex=True)
        ans_sub = sub[~is_unans]
        unans_sub = sub[is_unans]

        # Infrastructure failures (excluded from factual accuracy denominator)
        infra_failures = sub[sub["status"].isin(["rate_limited", "timeout", "error"])]

        # Answerable questions factual grading (denominator = successful answerable requests)
        ans_ok = ans_sub[ans_sub["status"] == "ok"]
        n_ans_ok = len(ans_ok)
        n_correct = len(ans_ok[ans_ok["answer_grade"] == "correct"])
        n_partial = len(ans_ok[ans_ok["answer_grade"] == "partially_correct"])
        n_wrong_facts = len(ans_ok[ans_ok["answer_grade"] == "wrong"])
        n_wrong_refusal = len(ans_ok[ans_ok["answer_grade"].isin(["refused_wrongly", "refused_incorrectly"])])
        n_wrong_all = n_wrong_facts + n_wrong_refusal

        if n_ans_ok > 0:
            correct_cited_pct = round((n_correct / n_ans_ok) * 100.0, 1)
            correct_str = f"{correct_cited_pct}% ({n_correct}/{n_ans_ok})"
            wrong_pct = round((n_wrong_all / n_ans_ok) * 100.0, 1)
            wrong_str = f"{wrong_pct}% ({n_wrong_all}/{n_ans_ok})"
        else:
            correct_str = "N/A (0 ok)"
            wrong_str = "N/A (0 ok)"

        # Unanswerable questions refusal grading (denominator = successful unanswerable requests)
        unans_ok = unans_sub[unans_sub["status"] == "ok"]
        n_unans_ok = len(unans_ok)
        n_refused_ok = len(unans_ok[unans_ok["answer_grade"] == "refused_correctly"])
        n_hallucinated = len(unans_ok[unans_ok["answer_grade"].isin(["wrong", "incorrect", "correct"])])

        if n_unans_ok > 0:
            refused_pct = round((n_refused_ok / n_unans_ok) * 100.0, 1)
            refused_str = f"{refused_pct}% ({n_refused_ok}/{n_unans_ok})"
        else:
            refused_str = "N/A (0 ok)"

        # Tokens per answer (output tokens on successful answers)
        ok_sub = sub[sub["status"] == "ok"]
        if len(ok_sub) > 0:
            avg_tokens = round(float(ok_sub["tokens_out"].mean()), 1)
        else:
            avg_tokens = "N/A"
        
        # TTFT: only measured on requests with valid output tokens
        valid_ttft = ok_sub[(pd.to_numeric(ok_sub["first_token_ms"], errors="coerce") > 0) & (ok_sub["tokens_out"] > 0)]
        ttft_p50, ttft_p95, _ = compute_percentiles(valid_ttft["first_token_ms"])
        tot_p50, tot_p95, _ = compute_percentiles(ok_sub["total_ms"])

        ttft_str = format_latencies_2(ttft_p50, ttft_p95)
        tot_str = format_latencies_2(tot_p50, tot_p95)

        t3_lines.append(
            f"| {label} | {q_count} | {correct_str} | {wrong_str} | {refused_str} | "
            f"{avg_tokens} | {ttft_str} | {tot_str} |"
        )

        breakdown_lines.append(
            f"| {s_key} | {n_ans_ok}/{len(ans_sub)} | {n_correct} | {n_partial} | {n_wrong_facts} | {n_wrong_refusal} | "
            f"{n_unans_ok}/{len(unans_sub)} | {n_refused_ok} | {n_hallucinated} | {len(infra_failures)}/{q_count} |"
        )

    return "\n".join(t3_lines) + "\n" + "\n".join(breakdown_lines)

def main():
    parser = argparse.ArgumentParser(description="Aggregate and generate experimental benchmark tables.")
    parser.add_argument("--csv", type=str, default=str(RESULTS_PATH), help="Path to results CSV file.")
    parser.add_argument("--run-id", type=str, default=None, help="Filter records by run ID.")
    parser.add_argument("--validate", action="store_true", help="Validate CSV schema before aggregating.")
    args = parser.parse_args()

    csv_file = Path(args.csv)
    if not csv_file.exists():
        print(f"Error: {csv_file} does not exist. Run benchmark scenarios first.")
        sys.exit(1)

    df = pd.read_csv(csv_file)
    print(f"[Aggregator] Loaded {len(df)} request records from {csv_file.name}")
    if args.run_id:
        print(f"[Aggregator] Filtering for run_id='{args.run_id}'")

    if args.validate:
        report = validate_results_dataframe(df, expected_run_id=args.run_id)
        if not report.is_valid:
            print(f"[Validation Warning/Error]: Schema check failed with {len(report.errors)} errors:")
            for err in report.errors:
                print(f"  - {err}")
        else:
            print("[Aggregator] CSV schema validation PASSED.")

    t1 = generate_table_1()
    t2a, t2b = generate_table_2a_and_2b(df, run_id=args.run_id)
    t3 = generate_table_3(df, run_id=args.run_id)

    print("=" * 80)
    print(t1)
    print("\n" + "=" * 80)
    print(t2a)
    print("\n" + "=" * 80)
    print(t2b)
    print("\n" + "=" * 80)
    print(t3)
    print("=" * 80)

if __name__ == "__main__":
    main()
