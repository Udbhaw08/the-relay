"""
Traffic Generator simulating the 5 required load scenarios:
steady, burst, sustained_overload, per_minute_halved, daily_budget_exhausted,
and independent, reproducible retrieval setting benchmarks.
"""
import time
import concurrent.futures
from typing import Optional
from the_relay.config import DEFAULT_SETTING
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS
from the_relay.traffic.logger import ResultsLogger

class TrafficGenerator:
    def __init__(self, pipeline: Optional[RelayPipeline] = None, logger: Optional[ResultsLogger] = None):
        self.pipeline = pipeline or RelayPipeline()
        self.logger = logger or ResultsLogger()

    def run_scenario_steady(
        self, num_requests: int = 15, source: str = "real", run_id: Optional[str] = None
    ) -> list[PipelineResult]:
        """
        Scenario 1: Steady load within free tier limits.
        Dispatches requests with a smooth inter-arrival delay (~4.2s = ~14 RPM).
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: STEADY (Source={source}, Requests={num_requests}, run_id={effective_run_id})...")
        results = []
        for i in range(num_requests):
            bq = BENCHMARK_QUESTIONS[i % len(BENCHMARK_QUESTIONS)]
            req_id = f"steady_{source}_{i+1:03d}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario="steady",
                source=source,
                retrieval_setting="setting_b",
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            results.append(res)
            print(f"  -> [{req_id}] TTFT={res.first_token_ms}ms, Total={res.total_ms}ms, Status={res.status}")

            # Rate pacing to avoid triggering 429 on steady state
            if source in ("real", "groq") and i < num_requests - 1:
                time.sleep(4.2)
            else:
                time.sleep(0.5)

        return results

    def run_scenario_burst(
        self, num_requests: int = 25, source: str = "stand-in", run_id: Optional[str] = None
    ) -> list[PipelineResult]:
        """
        Scenario 2: Sudden burst.
        Submits concurrent requests simultaneously to stress queue and concurrency limiters.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: BURST (Source={source}, Concurrent={num_requests}, run_id={effective_run_id})...")
        results = []

        def _worker(idx: int):
            bq = BENCHMARK_QUESTIONS[idx % len(BENCHMARK_QUESTIONS)]
            req_id = f"burst_{source}_{idx+1:03d}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario="burst",
                source=source,
                retrieval_setting="setting_b",
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(num_requests, 10)) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_requests)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    results.append(res)
                    print(f"  -> [{res.request_id}] Status={res.status}, TTFT={res.first_token_ms}ms, Retries={res.retries}")
                except Exception as e:
                    print(f"  -> Burst worker error: {e}")

        return results

    def run_scenario_sustained_overload(
        self, num_requests: int = 30, source: str = "stand-in", run_id: Optional[str] = None
    ) -> list[PipelineResult]:
        """
        Scenario 3: Sustained overload.
        Continuous flood of requests arriving faster than the system can process.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: SUSTAINED OVERLOAD (Source={source}, Requests={num_requests}, run_id={effective_run_id})...")
        results = []

        def _worker(idx: int):
            time.sleep(idx * 0.4)
            bq = BENCHMARK_QUESTIONS[idx % len(BENCHMARK_QUESTIONS)]
            req_id = f"sustained_{source}_{idx+1:03d}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario="sustained_overload",
                source=source,
                retrieval_setting="setting_b",
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_requests)]
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                results.append(res)
                print(f"  -> [{res.request_id}] Status={res.status}, Total={res.total_ms}ms")

        return results

    def run_scenario_per_minute_halved(
        self, num_requests: int = 20, source: str = "stand-in", run_id: Optional[str] = None
    ) -> list[PipelineResult]:
        """
        Scenario 4: Per-minute limit halved.
        Tests how the system throttles and queues when the provider cuts RPM quota by 50%.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: PER-MINUTE LIMIT HALVED (Source={source}, run_id={effective_run_id})...")
        if source in ("stand-in", "standin"):
            self.pipeline.router.stand_in_client.halve_rpm_limit()
        results = []

        for i in range(num_requests):
            bq = BENCHMARK_QUESTIONS[i % len(BENCHMARK_QUESTIONS)]
            req_id = f"halved_{source}_{i+1:03d}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario="per_minute_limit_halved",
                source=source,
                retrieval_setting="setting_b",
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            results.append(res)
            print(f"  -> [{req_id}] Status={res.status}, Retries={res.retries}, Total={res.total_ms}ms")
            time.sleep(1.0)

        return results

    def run_scenario_daily_budget_exhausted(
        self, num_requests: int = 15, source: str = "stand-in", run_id: Optional[str] = None
    ) -> list[PipelineResult]:
        """
        Scenario 5: Daily budget exhausted (At 3 PM scenario).
        All incoming requests encounter exhausted daily quota and receive graceful notices.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: DAILY BUDGET EXHAUSTED (Source={source}, run_id={effective_run_id})...")
        if source in ("stand-in", "standin"):
            self.pipeline.router.stand_in_client.exhaust_daily_budget()
        results = []

        for i in range(num_requests):
            bq = BENCHMARK_QUESTIONS[i % len(BENCHMARK_QUESTIONS)]
            req_id = f"daily_exhausted_{source}_{i+1:03d}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario="daily_budget_exhausted",
                source=source,
                retrieval_setting="setting_b",
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            results.append(res)
            print(f"  -> [{req_id}] Status={res.status}, Notice: {res.answer[:80]}...")
            time.sleep(0.2)

        return results

    def run_retrieval_setting_benchmark(
        self,
        setting_key: str,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        random_seed: Optional[int] = 42
    ) -> list[PipelineResult]:
        """
        Run all 15 benchmark questions through a specific retrieval setting (for Table 3).
        Guarantees independent experiment context, clean rate limit state, and fixed random seed.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Evaluating Retrieval Benchmark on {setting_key} (Source={source}, run_id={effective_run_id})...")

        # Isolate and reset simulator state for each setting so A does not contaminate B or C
        if source in ("stand-in", "standin"):
            self.pipeline.router.stand_in_client.reset_quota_state()
            if random_seed is not None:
                self.pipeline.router.stand_in_client.set_seed(random_seed)

        results = []
        for bq in BENCHMARK_QUESTIONS:
            req_id = f"eval_{setting_key}_{bq.id}"
            res = self.pipeline.run_request(
                query=bq.question,
                request_id=req_id,
                scenario=f"eval_{setting_key}",
                source=source,
                retrieval_setting=setting_key,
                expected_negative=bq.expected_negative,
                run_id=effective_run_id,
                question_id=bq.id,
                ground_truth_key_facts=bq.ground_truth_key_facts
            )
            self.logger.log_result(res)
            results.append(res)
        return results
