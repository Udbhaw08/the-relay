"""
Main execution runner to conduct all load scenarios and retrieval benchmarks.
Populates results.csv and computes Tables 1, 2a, 2b, 3 with full experiment isolation.
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Add root directory to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.config import RESULTS_PATH, RETRIEVAL_SETTINGS, GROQ_MODEL, LLM_PROVIDER
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS
from the_relay.pipeline.orchestrator import RelayPipeline
from the_relay.traffic.generator import TrafficGenerator
from the_relay.traffic.logger import ResultsLogger
from scripts.compute_tables import (
    generate_table_1,
    generate_table_2a_and_2b,
    generate_table_3
)
import pandas as pd

def get_git_commit_sha() -> str:
    """Safely get current Git commit SHA."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown_commit"

def save_run_manifest(run_id: str, seed: int, csv_path: Path, offline_only: bool) -> Path:
    """Save immutable run configuration snapshot and metadata."""
    manifest_dir = ROOT_DIR / "data" / "runs" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / "manifest.json"

    manifest_data = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "git_commit": get_git_commit_sha(),
        "random_seed": seed,
        "offline_only": offline_only,
        "configured_llm_provider": LLM_PROVIDER,
        "configured_groq_model": GROQ_MODEL,
        "retrieval_settings": RETRIEVAL_SETTINGS,
        "benchmark_questions_count": len(BENCHMARK_QUESTIONS),
        "benchmark_question_ids": [q.id for q in BENCHMARK_QUESTIONS],
        "output_csv": str(csv_path.resolve())
    }

    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return manifest_file

def main():
    parser = argparse.ArgumentParser(description="Run complete or isolated benchmark suite.")
    parser.add_argument("--run-id", type=str, default=None, help="Identifier for this benchmark run.")
    parser.add_argument("--csv", type=str, default=str(RESULTS_PATH), help="Target CSV file for results.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic stand-in simulation.")
    parser.add_argument("--offline-only", action="store_true", default=True, help="Run exclusively offline without live provider calls.")
    args = parser.parse_args()

    run_id = args.run_id or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    target_csv = Path(args.csv)

    print("=" * 80)
    print(f"THE RELAY: EXECUTING BENCHMARKS & LOAD SCENARIOS [Run ID: {run_id}]")
    print(f"Target CSV: {target_csv.name} | Random Seed: {args.seed} | Offline Only: {args.offline_only}")
    print("=" * 80)

    # Save manifest snapshot
    manifest_path = save_run_manifest(run_id=run_id, seed=args.seed, csv_path=target_csv, offline_only=args.offline_only)
    print(f"[Manifest] Experiment snapshot saved to: {manifest_path.relative_to(ROOT_DIR)}")

    pipeline = RelayPipeline()
    logger = ResultsLogger(file_path=target_csv, run_id=run_id)
    generator = TrafficGenerator(pipeline=pipeline, logger=logger)

    # 1. Steady Load Scenario
    print("\n>>> Phase A: Steady Load Scenario")
    if not args.offline_only:
        print("Running live steady load against configured provider (requires authorized key & Free tier)...")
        generator.run_scenario_steady(num_requests=10, source="real", run_id=run_id)
    else:
        print("Running steady load in stand-in mode (offline safety default)...")
        generator.run_scenario_steady(num_requests=10, source="stand-in", run_id=run_id)

    # 2. Retrieval Settings Benchmarks (Settings A, B, C) - Isolated Quota & Seeds
    print("\n>>> Phase B: Retrieval Settings Evaluation (Table 3 - Independent Isolation)")
    generator.run_retrieval_setting_benchmark(setting_key="setting_a", source="stand-in", run_id=run_id, random_seed=args.seed)
    generator.run_retrieval_setting_benchmark(setting_key="setting_b", source="stand-in", run_id=run_id, random_seed=args.seed)
    generator.run_retrieval_setting_benchmark(setting_key="setting_c", source="stand-in", run_id=run_id, random_seed=args.seed)

    # 3. Burst Load Scenario (Stand-In Simulator)
    print("\n>>> Phase C: Burst Load Scenario (Stand-In Simulator)")
    generator.run_scenario_burst(num_requests=20, source="stand-in", run_id=run_id)

    # 4. Sustained Overload Scenario (Stand-In Simulator)
    print("\n>>> Phase D: Sustained Overload Scenario (Stand-In Simulator)")
    generator.run_scenario_sustained_overload(num_requests=25, source="stand-in", run_id=run_id)

    # 5. Per-Minute Limit Halved Scenario (Stand-In Simulator)
    print("\n>>> Phase E: Per-Minute Limit Halved Scenario (Stand-In Simulator)")
    generator.run_scenario_per_minute_halved(num_requests=15, source="stand-in", run_id=run_id)

    # 6. Daily Budget Exhausted Scenario (Stand-In Simulator)
    print("\n>>> Phase F: Daily Budget Exhausted Scenario (Stand-In Simulator)")
    generator.run_scenario_daily_budget_exhausted(num_requests=10, source="stand-in", run_id=run_id)

    print("\n" + "=" * 80)
    print(f"BENCHMARK RUN '{run_id}' COMPLETED. COMPUTING SUMMARY TABLES...")
    print("=" * 80 + "\n")

    df = pd.read_csv(target_csv)
    t1 = generate_table_1()
    t2a, t2b = generate_table_2a_and_2b(df, run_id=run_id)
    t3 = generate_table_3(df, run_id=run_id)

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
