"""
Execute live benchmarks against GroqCloud API (openai/gpt-oss-20b).
Generates verified live data in data/runs/live_groq_verified/results.csv.
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.config import GROQ_MODEL, RETRIEVAL_SETTINGS
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

def main():
    run_id = "live_groq_verified"
    run_dir = ROOT_DIR / "data" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    target_csv = run_dir / "results.csv"
    manifest_path = run_dir / "manifest.json"

    if target_csv.exists():
        target_csv.unlink()

    print("=" * 80)
    print(f"THE RELAY: LIVE GROQCLOUD BENCHMARK [Run ID: {run_id}]")
    print(f"Target Model: {GROQ_MODEL} | Destination: {target_csv.name}")
    print("=" * 80)

    # 1. Manifest
    manifest_data = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "offline_only": False,
        "configured_llm_provider": "groq",
        "configured_groq_model": GROQ_MODEL,
        "retrieval_settings": RETRIEVAL_SETTINGS,
        "benchmark_questions_count": len(BENCHMARK_QUESTIONS),
        "benchmark_question_ids": [q.id for q in BENCHMARK_QUESTIONS],
        "output_csv": str(target_csv.relative_to(ROOT_DIR)).replace("\\", "/")
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    t_start = time.perf_counter()
    pipeline = RelayPipeline()
    logger = ResultsLogger(file_path=target_csv, run_id=run_id)
    generator = TrafficGenerator(pipeline=pipeline, logger=logger)

    # 2. Live Steady Scenario (5 requests with 4.2s pacing)
    print("\n>>> Phase 1: Live Steady Load Scenario (GroqCloud)")
    generator.run_scenario_steady(
        num_requests=5,
        source="groq",
        run_id=run_id,
        target_interval=4.5,
        max_concurrency=2
    )

    # 3. Live Retrieval Quality Evaluation on Setting B (15 questions with 6s pacing)
    print("\n>>> Phase 2: Live Pure Retrieval Benchmark on Setting B (15 questions)")
    generator.run_retrieval_setting_benchmark(
        setting_key="setting_b",
        source="groq",
        run_id=run_id,
        pacing_delay=6.0
    )

    # 4. Stand-in Reference on Setting A and Setting C (to preserve complete comparative Table 3)
    print("\n>>> Phase 3: Stand-in Comparative Reference (Setting A & Setting C)")
    generator.run_retrieval_setting_benchmark(
        setting_key="setting_a",
        source="stand-in",
        run_id=run_id,
        pacing_delay=0.0
    )
    generator.run_retrieval_setting_benchmark(
        setting_key="setting_c",
        source="stand-in",
        run_id=run_id,
        pacing_delay=0.0
    )

    # 5. Stand-in Reference for Stress Scenarios (Burst, Sustained, Halved, Daily)
    print("\n>>> Phase 4: Stress Fault-Injection Reference Scenarios (Stand-In Simulator)")
    generator.run_scenario_burst(num_requests=20, source="stand-in", run_id=run_id)
    generator.run_scenario_sustained_overload(num_requests=25, source="stand-in", run_id=run_id)
    generator.run_scenario_per_minute_halved(num_requests=15, source="stand-in", run_id=run_id)
    generator.run_scenario_daily_budget_exhausted(num_requests=10, source="stand-in", run_id=run_id)

    t_end = time.perf_counter()
    duration_sec = round(t_end - t_start, 2)

    manifest_data["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest_data["duration_seconds"] = duration_sec
    manifest_data["steady_stats"] = generator.last_steady_stats
    manifest_data["burst_accounting"] = generator.last_burst_stats
    manifest_data["sustained_stats"] = generator.last_sustained_stats
    manifest_data["halved_stats"] = generator.last_halved_stats

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print("\n" + "=" * 80)
    print(f"LIVE BENCHMARK COMPLETED in {duration_sec}s! Computing Tables...")
    print("=" * 80)

    df = pd.read_csv(target_csv)
    print(f"Total rows logged: {len(df)}")
    print(f"Live Groq rows:    {len(df[df['source'] == 'groq'])}")
    print(f"Stand-in rows:     {len(df[df['source'] == 'stand-in'])}")

    t1 = generate_table_1()
    t2a, t2b = generate_table_2a_and_2b(df)
    t3 = generate_table_3(df)

    print("\n" + t1)
    print("\n" + t2a)
    print("\n" + t2b)
    print("\n" + t3)

if __name__ == "__main__":
    main()
