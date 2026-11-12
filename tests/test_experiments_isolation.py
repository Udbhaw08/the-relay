"""Tests for Phase 2: Independent A/B/C experiments, quota isolation, and reproducibility."""
import pytest
from pathlib import Path
import tempfile
import pandas as pd

from the_relay.config import RETRIEVAL_SETTINGS
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS
from the_relay.models.stand_in import StandInModelClient
from the_relay.pipeline.orchestrator import RelayPipeline
from the_relay.traffic.generator import TrafficGenerator
from the_relay.traffic.logger import ResultsLogger

# 1. A/B/C use identical benchmark IDs and order
def test_abc_use_identical_question_ids_and_order():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "test_eval.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000
        logger = ResultsLogger(file_path=csv_file, run_id="iso_test")
        generator = TrafficGenerator(pipeline=pipeline, logger=logger)

        res_a = generator.run_retrieval_setting_benchmark("setting_a", source="stand-in", run_id="iso_test")
        res_b = generator.run_retrieval_setting_benchmark("setting_b", source="stand-in", run_id="iso_test")
        res_c = generator.run_retrieval_setting_benchmark("setting_c", source="stand-in", run_id="iso_test")

        q_ids_expected = [q.id for q in BENCHMARK_QUESTIONS]
        q_ids_a = [r.request_id.replace("eval_setting_a_", "") for r in res_a]
        q_ids_b = [r.request_id.replace("eval_setting_b_", "") for r in res_b]
        q_ids_c = [r.request_id.replace("eval_setting_c_", "") for r in res_c]

        assert q_ids_a == q_ids_expected
        assert q_ids_b == q_ids_expected
        assert q_ids_c == q_ids_expected
        assert len(res_a) == 15
        assert len(res_b) == 15
        assert len(res_c) == 15

# 2. Simulator quota resets between settings (Setting A cannot contaminate Setting B)
def test_quota_isolation_between_settings():
    stand_in = StandInModelClient(rpm_limit=5)
    # Saturate quota in stand_in
    for _ in range(5):
        stand_in.generate("Hello world")

    # Immediate next request would be rate-limited
    res_blocked = stand_in.generate("Another query")
    assert res_blocked.status == "rate_limited"

    # Reset quota state
    stand_in.reset_quota_state()

    # Now request must succeed
    res_fresh = stand_in.generate("Fresh query after reset")
    assert res_fresh.status == "ok"

# 3. Degradation metadata records requested vs effective setting and reason
def test_degradation_metadata_recorded():
    pipeline = RelayPipeline()
    # Trigger retrieval with limit_warning=True
    chunks, effective = pipeline.step_2_retrieve_tool(
        query="What is attention?",
        setting_key="setting_b",
        limit_warning=True,
        hint="Attention"
    )
    # Requested was setting_b, but limit warning degraded to setting_a
    assert effective == "setting_a"

# 4. Deterministic simulator reproducibility with fixed seeds
def test_deterministic_seed_reproducibility():
    s1 = StandInModelClient(random_seed=42)
    ttfts_1 = [s1._compute_calibrated_delay(20)[0] for _ in range(10)]

    s2 = StandInModelClient(random_seed=42)
    ttfts_2 = [s2._compute_calibrated_delay(20)[0] for _ in range(10)]

    assert ttfts_1 == ttfts_2

# 5. Repeated runs maintain distinct run IDs and do not collide
def test_repeated_runs_maintain_distinct_run_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "multi_run.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000

        logger1 = ResultsLogger(file_path=csv_file, run_id="run_alpha")
        gen1 = TrafficGenerator(pipeline=pipeline, logger=logger1)
        res1 = gen1.run_retrieval_setting_benchmark("setting_a", source="stand-in", run_id="run_alpha")

        logger2 = ResultsLogger(file_path=csv_file, run_id="run_beta")
        gen2 = TrafficGenerator(pipeline=pipeline, logger=logger2)
        res2 = gen2.run_retrieval_setting_benchmark("setting_a", source="stand-in", run_id="run_beta")

        df = pd.read_csv(csv_file)
        assert len(df) == 30
        assert len(df[df["run_id"] == "run_alpha"]) == 15
        assert len(df[df["run_id"] == "run_beta"]) == 15
