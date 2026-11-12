"""Unit and integration tests for Phase 8: Load Generator, Scenarios, and Reproducible Benchmarks."""
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pandas as pd
import pytest

from the_relay.traffic.generator import TrafficGenerator, ConcurrencyTracker
from the_relay.traffic.logger import ResultsLogger
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult
from the_relay.models.stand_in import StandInModelClient
from scripts.run_benchmarks import save_run_manifest, update_run_manifest
from scripts.compute_tables import generate_table_2a_and_2b, generate_table_3

# 1. Steady start-to-start interval pacing
def test_steady_start_to_start_pacing():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "steady_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        logger = ResultsLogger(file_path=csv_file, run_id="steady_pace_run")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)

        t0 = time.perf_counter()
        target_interval = 0.05  # 50ms interval for fast unit test
        results = gen.run_scenario_steady(
            num_requests=4,
            source="stand-in",
            run_id="steady_pace_run",
            target_interval=target_interval
        )
        t_total = time.perf_counter() - t0

        assert len(results) == 4
        # Total time should be roughly 3 intervals (0s, 0.05s, 0.10s, 0.15s) >= 0.14s
        assert t_total >= (3 * target_interval) * 0.85

# 2. ConcurrencyTracker admission and outcome accounting
def test_concurrency_tracker_admission_accounting():
    tracker = ConcurrencyTracker(max_concurrency=2, max_queue=3)

    # Submit 3 tasks (should all be admitted to queue)
    adm1, t1 = tracker.submit_task()
    adm2, t2 = tracker.submit_task()
    adm3, t3 = tracker.submit_task()
    assert adm1 and adm2 and adm3
    assert tracker.offered_count == 3
    assert tracker.submitted_count == 3
    assert tracker.rejected_count == 0

    # 4th task exceeds max_queue=3 -> rejected
    adm4, t4 = tracker.submit_task()
    assert not adm4
    assert tracker.offered_count == 4
    assert tracker.submitted_count == 3
    assert tracker.rejected_count == 1

    # Start 2 tasks
    wait1, q1, in1 = tracker.start_task(t1)
    wait2, q2, in2 = tracker.start_task(t2)
    assert in2 == 2
    assert tracker.accepted_count == 2

    # Finish tasks
    tracker.finish_task(status="ok")
    tracker.finish_task(status="rate_limited")
    stats = tracker.stats()
    assert stats["successful_count"] == 1
    assert stats["failed_count"] == 1
    assert stats["max_concurrency"] == 2

# 3. Burst scenario records admission accounting and backpressure
def test_burst_scenario_accounting_and_backpressure():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "burst_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000
        logger = ResultsLogger(file_path=csv_file, run_id="burst_acc_run")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)

        results = gen.run_scenario_burst(
            num_requests=15, source="stand-in", run_id="burst_acc_run", sleeper=lambda _: None
        )
        assert len(results) == 15
        stats = gen.last_burst_stats
        assert stats["offered_count"] == 15
        assert stats["submitted_count"] + stats["rejected_count"] == 15
        assert stats["successful_count"] + stats["failed_count"] + stats["rejected_count"] == 15

# 4. Sustained overload scenario measures bounded queue and concurrency
def test_sustained_overload_scenario():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "sustained_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000
        logger = ResultsLogger(file_path=csv_file, run_id="sustained_run")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)

        results = gen.run_scenario_sustained_overload(
            num_requests=20, source="stand-in", run_id="sustained_run", sleeper=lambda _: None
        )
        assert len(results) == 20
        stats = gen.last_sustained_stats
        assert stats["max_concurrency"] <= 5
        assert stats["peak_queue_depth"] <= 15

# 5. Per-minute limit halved triggers throttling
def test_per_minute_limit_halved_scenario():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "halved_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000
        initial_rpm = pipeline.router.stand_in_client.rpm_limit

        logger = ResultsLogger(file_path=csv_file, run_id="halved_run")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)
        results = gen.run_scenario_per_minute_halved(
            num_requests=6, source="stand-in", run_id="halved_run", sleeper=lambda _: None, pacing_delay=0.0
        )

        assert len(results) == 6
        assert pipeline.router.stand_in_client.rpm_limit == max(1, initial_rpm // 2)

# 6. Daily budget exhaustion scenario denies requests with 0 retry loop
def test_daily_budget_exhaustion_scenario_zero_retries():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "daily_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        logger = ResultsLogger(file_path=csv_file, run_id="daily_run")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)

        results = gen.run_scenario_daily_budget_exhausted(
            num_requests=5, source="stand-in", run_id="daily_run", pacing_delay=0.0
        )
        assert len(results) == 5
        for r in results:
            assert r.status in ("rate_limited", "error")
            assert r.retries == 0  # Crucial: daily budget must NOT spin retry loop
            assert "daily" in (r.answer or "").lower() or "budget" in (r.answer or "").lower()

# 7. Run manifest captures execution metadata, timestamps, and accounting
def test_run_manifest_metadata_and_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "manifest_test.csv"
        run_id = "test_run_manifest_123"
        manifest_path = save_run_manifest(
            run_id=run_id,
            seed=42,
            csv_path=csv_file,
            offline_only=True
        )
        assert manifest_path.exists()

        update_run_manifest(
            manifest_path=manifest_path,
            extra_data={
                "duration_seconds": 12.34,
                "burst_accounting": {"offered": 20, "accepted": 18, "rejected": 2}
            }
        )

        import json
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["run_id"] == run_id
        assert data["random_seed"] == 42
        assert data["offline_only"] is True
        assert data["duration_seconds"] == 12.34
        assert "completed_at" in data
        assert data["burst_accounting"]["rejected"] == 2

        # Clean up test manifest directory
        import shutil
        if manifest_path.parent.exists():
            shutil.rmtree(manifest_path.parent, ignore_errors=True)

# 8. Table 2a and 2b computation with valid samples and run_id filtering
def test_table_2_and_3_with_run_scoped_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "tables_test.csv"
        pipeline = RelayPipeline()
        pipeline.router.stand_in_client.fast_mode = True
        pipeline.router.stand_in_client.rpm_limit = 1000
        logger = ResultsLogger(file_path=csv_file, run_id="scoped_run_1")
        gen = TrafficGenerator(pipeline=pipeline, logger=logger)

        # Run steady scenario
        gen.run_scenario_steady(num_requests=3, source="stand-in", run_id="scoped_run_1", target_interval=0.01)
        # Run retrieval setting A
        gen.run_retrieval_setting_benchmark(setting_key="setting_a", source="stand-in", run_id="scoped_run_1")

        df = pd.read_csv(csv_file)
        t2a, t2b = generate_table_2a_and_2b(df, run_id="scoped_run_1")
        t3 = generate_table_3(df, run_id="scoped_run_1")

        assert "### Table 2a:" in t2a
        assert "steady" in t2a
        assert "### Table 2b:" in t2b
        assert "### Table 3:" in t3
        assert "Piece size 250" in t3
