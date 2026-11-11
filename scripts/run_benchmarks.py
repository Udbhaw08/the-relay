"""
Main execution runner to conduct all load scenarios and retrieval benchmarks.
Populates results.csv and computes Tables 1, 2a, 2b, 3.
"""
import sys
import time
from pathlib import Path

# Add root directory to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.pipeline.orchestrator import RelayPipeline
from the_relay.traffic.generator import TrafficGenerator
from the_relay.traffic.logger import ResultsLogger
from scripts.compute_tables import main as compute_tables_main

def main():
    print("=" * 80)
    print("THE RELAY: EXECUTING BENCHMARKS & LOAD SCENARIOS")
    print("=" * 80)

    pipeline = RelayPipeline()
    logger = ResultsLogger()
    generator = TrafficGenerator(pipeline=pipeline, logger=logger)

    # 1. Steady Load Scenario (Real Service)
    print("\n>>> Phase A: Real Service Probes (Steady Scenario)")
    # 10 requests paced at ~4s apart to respect the 15 RPM free tier limit
    generator.run_scenario_steady(num_requests=10, source="real")

    # 2. Retrieval Settings Benchmarks (Settings A, B, C)
    print("\n>>> Phase B: Retrieval Settings Evaluation (Table 3)")
    generator.run_retrieval_setting_benchmark(setting_key="setting_a", source="stand-in")
    generator.run_retrieval_setting_benchmark(setting_key="setting_b", source="stand-in")
    generator.run_retrieval_setting_benchmark(setting_key="setting_c", source="stand-in")

    # 3. Burst Load Scenario (Stand-In Simulator)
    print("\n>>> Phase C: Burst Load Scenario (Stand-In Simulator)")
    generator.run_scenario_burst(num_requests=20, source="stand-in")

    # 4. Sustained Overload Scenario (Stand-In Simulator)
    print("\n>>> Phase D: Sustained Overload Scenario (Stand-In Simulator)")
    generator.run_scenario_sustained_overload(num_requests=25, source="stand-in")

    # 5. Per-Minute Limit Halved Scenario (Stand-In Simulator)
    print("\n>>> Phase E: Per-Minute Limit Halved Scenario (Stand-In Simulator)")
    generator.run_scenario_per_minute_halved(num_requests=15, source="stand-in")

    # 6. Daily Budget Exhausted Scenario (Stand-In Simulator)
    print("\n>>> Phase F: Daily Budget Exhausted Scenario (Stand-In Simulator)")
    generator.run_scenario_daily_budget_exhausted(num_requests=10, source="stand-in")

    print("\n" + "=" * 80)
    print("ALL BENCHMARK RUNS COMPLETED. COMPUTING FINAL RESULTS TABLES...")
    print("=" * 80 + "\n")

    compute_tables_main()

if __name__ == "__main__":
    main()

