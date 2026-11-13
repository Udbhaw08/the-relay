"""
Traffic Generator simulating the 5 required load scenarios:
steady, burst, sustained_overload, per_minute_halved, daily_budget_exhausted,
and independent, reproducible retrieval setting benchmarks.
"""
import time
import threading
import concurrent.futures
from typing import Optional, Any
from the_relay.config import DEFAULT_SETTING
from the_relay.pipeline.orchestrator import RelayPipeline, PipelineResult
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS
from the_relay.traffic.logger import ResultsLogger

class ConcurrencyTracker:
    """Thread-safe monitor tracking queue wait, queue depth, active concurrency, and admission accounting."""
    def __init__(self, max_concurrency: int = 10, max_queue: int = 50):
        self._lock = threading.Lock()
        self.max_concurrency = max_concurrency
        self.max_queue = max_queue
        self._queue_depth = 0
        self._peak_queue_depth = 0
        self._in_flight = 0
        self._max_concurrency = 0
        self.offered_count = 0
        self.submitted_count = 0
        self.accepted_count = 0
        self.rejected_count = 0
        self.successful_count = 0
        self.failed_count = 0

    def submit_task(self) -> tuple[bool, float]:
        """
        Record task submission. Returns (admitted, monotonic_timestamp).
        If queue is at capacity, rejects with backpressure.
        """
        with self._lock:
            self.offered_count += 1
            if self._queue_depth >= self.max_queue:
                self.rejected_count += 1
                return False, time.perf_counter()
            self.submitted_count += 1
            self._queue_depth += 1
            if self._queue_depth > self._peak_queue_depth:
                self._peak_queue_depth = self._queue_depth
            return True, time.perf_counter()

    def start_task(self, submit_time: Any) -> tuple[float, int, int]:
        """Record task admission into active execution. Returns (wait_ms, admission_queue_depth, in_flight)."""
        ts = submit_time[1] if isinstance(submit_time, tuple) else float(submit_time)
        with self._lock:
            self.accepted_count += 1
            admission_depth = self._queue_depth
            self._queue_depth = max(0, self._queue_depth - 1)
            self._in_flight += 1
            if self._in_flight > self._max_concurrency:
                self._max_concurrency = self._in_flight
            wait_ms = max(0.0, (time.perf_counter() - ts) * 1000.0)
            return wait_ms, admission_depth, self._in_flight

    def finish_task(self, status: str = "ok"):
        """Record task completion and count outcomes."""
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            if status == "ok":
                self.successful_count += 1
            else:
                self.failed_count += 1

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "offered_count": self.offered_count,
                "submitted_count": self.submitted_count,
                "accepted_count": self.accepted_count,
                "rejected_count": self.rejected_count,
                "successful_count": self.successful_count,
                "failed_count": self.failed_count,
                "peak_queue_depth": self._peak_queue_depth,
                "max_concurrency": self._max_concurrency
            }

class TrafficGenerator:
    def __init__(self, pipeline: Optional[RelayPipeline] = None, logger: Optional[ResultsLogger] = None):
        self.pipeline = pipeline or RelayPipeline()
        self.logger = logger or ResultsLogger()
        self.last_burst_stats: dict[str, Any] = {}
        self.last_sustained_stats: dict[str, Any] = {}
        self.last_steady_stats: dict[str, Any] = {}
        self.last_halved_stats: dict[str, Any] = {}

    def run_scenario_steady(
        self,
        num_requests: int = 15,
        source: str = "real",
        run_id: Optional[str] = None,
        target_interval: Optional[float] = None,
        max_concurrency: Optional[int] = None,
        max_queue: Optional[int] = None
    ) -> list[PipelineResult]:
        """
        Scenario 1: Steady load within free tier limits.
        Dispatches requests with exact monotonic start-to-start inter-arrival scheduling
        using a bounded concurrent scheduler.
        Dispatches each request at its intended target time without waiting for prior requests.
        Respects MAX_CONCURRENT_REQUESTS and MAX_QUEUE_CAPACITY to prevent unbounded backlog.
        """
        from the_relay.config import MAX_CONCURRENT_REQUESTS, MAX_QUEUE_CAPACITY
        effective_run_id = run_id or "default_run"
        if target_interval is None:
            target_interval = 4.2 if source in ("real", "groq") else 1.0

        concurrency_limit = max_concurrency or MAX_CONCURRENT_REQUESTS
        queue_limit = max_queue or MAX_QUEUE_CAPACITY

        print(f"\n[TrafficGenerator] Running Scenario: STEADY (Source={source}, Requests={num_requests}, Interval={target_interval}s, MaxConcurrency={concurrency_limit}, MaxQueue={queue_limit}, run_id={effective_run_id})...")
        tracker = ConcurrencyTracker(max_concurrency=concurrency_limit, max_queue=queue_limit)
        results: list[PipelineResult] = []
        futures = []
        schedule_start_perf = time.perf_counter()
        actual_dispatch_times: list[float] = []
        dispatch_latenesses_ms: list[float] = []

        def _worker(idx: int, admitted: bool, t_submit: float, target_start: float, lateness: float):
            bq = BENCHMARK_QUESTIONS[idx % len(BENCHMARK_QUESTIONS)]
            req_id = f"steady_{source}_{idx+1:03d}"
            sched_offset = round(target_start - schedule_start_perf, 3)
            disp_offset = round(t_submit - schedule_start_perf, 3)

            if not admitted:
                # Backpressure rejection if queue limit breached
                t_now = time.perf_counter()
                total_ms = max(0.1, round((t_now - t_submit) * 1000.0, 1))
                res = PipelineResult(
                    request_id=req_id,
                    scenario="steady",
                    source=source,
                    start_time=time.time(),
                    first_token_ms=None,
                    total_ms=total_ms,
                    status="rate_limited",
                    retries=0,
                    tokens_in=0,
                    tokens_out=0,
                    is_simulated=(source in ("stand-in", "standin")),
                    retrieval_setting="setting_b",
                    degradation_reason="queue_capacity_breached_backpressure",
                    answer_grade="rate_limited",
                    answer="Request rejected due to bounded queue capacity backpressure in steady scenario.",
                    run_id=effective_run_id,
                    queue_depth=tracker.max_queue,
                    admission_queue_depth=tracker.max_queue,
                    scheduled_offset_s=sched_offset,
                    dispatch_offset_s=disp_offset,
                    dispatch_lateness_ms=round(lateness, 1),
                    queue_arrival_time=t_submit,
                    timestamps={
                        "scheduled_start_perf": target_start,
                        "actual_dispatch_perf": t_submit,
                        "dispatch_lateness_ms": lateness
                    }
                )
                self.logger.log_result(res)
                return res

            wait_ms, q_depth, in_flight = tracker.start_task(t_submit)
            t_proc_start = time.perf_counter()
            try:
                res = self.pipeline.run_request(
                    query=bq.question,
                    request_id=req_id,
                    scenario="steady",
                    source=source,
                    retrieval_setting="setting_b",
                    expected_negative=bq.expected_negative,
                    run_id=effective_run_id,
                    question_id=bq.id,
                    ground_truth_key_facts=bq.ground_truth_key_facts,
                    queue_wait_ms=round(wait_ms, 1),
                    queue_depth=q_depth,
                    concurrency=in_flight
                )
                res.admission_queue_depth = q_depth
                res.scheduled_offset_s = sched_offset
                res.dispatch_offset_s = disp_offset
                res.dispatch_lateness_ms = round(lateness, 1)
                res.queue_arrival_time = t_submit
                res.processing_start_time = t_proc_start
                res.timestamps["scheduled_start_perf"] = target_start
                res.timestamps["actual_dispatch_perf"] = t_submit
                res.timestamps["dispatch_lateness_ms"] = lateness
                self.logger.log_result(res)
                return res
            finally:
                tracker.finish_task(res.status if 'res' in locals() else "error")

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency_limit) as executor:
            for i in range(num_requests):
                target_start = schedule_start_perf + (i * target_interval)
                now_perf = time.perf_counter()
                wait_for_slot = target_start - now_perf
                if wait_for_slot > 0:
                    time.sleep(wait_for_slot)

                dispatch_perf = time.perf_counter()
                lateness_ms = max(0.0, (dispatch_perf - target_start) * 1000.0)
                actual_dispatch_times.append(dispatch_perf)
                dispatch_latenesses_ms.append(lateness_ms)

                admitted, t_submit = tracker.submit_task()
                fut = executor.submit(_worker, i, admitted, t_submit, target_start, lateness_ms)
                futures.append(fut)

            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    results.append(res)
                    print(f"  -> [{res.request_id}] TTFT={res.first_token_ms}ms, Total={res.total_ms}ms, Status={res.status}")
                except Exception as e:
                    print(f"  -> Steady worker error: {e}")

        # Sort results deterministically by request_id
        results.sort(key=lambda r: r.request_id)

        # Calculate inter-arrival intervals
        intervals = [
            (actual_dispatch_times[j] - actual_dispatch_times[j - 1])
            for j in range(1, len(actual_dispatch_times))
        ] if len(actual_dispatch_times) > 1 else [0.0]

        mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
        mean_lateness = sum(dispatch_latenesses_ms) / len(dispatch_latenesses_ms) if dispatch_latenesses_ms else 0.0

        self.last_steady_stats = {
            **tracker.stats(),
            "target_interval_sec": target_interval,
            "mean_measured_interval_sec": round(mean_interval, 3),
            "mean_dispatch_lateness_ms": round(mean_lateness, 2),
            "min_measured_interval_sec": round(min(intervals), 3) if intervals else 0.0,
            "max_measured_interval_sec": round(max(intervals), 3) if intervals else 0.0,
        }
        print(f"  [Steady Scheduler Stats] MeanInterval={self.last_steady_stats['mean_measured_interval_sec']}s (target={target_interval}s), MeanLateness={self.last_steady_stats['mean_dispatch_lateness_ms']}ms, MaxConcurrency={self.last_steady_stats['max_concurrency']}")
        return results

    def run_scenario_burst(
        self,
        num_requests: int = 25,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        sleeper: Optional[Any] = None
    ) -> list[PipelineResult]:
        """
        Scenario 2: Sudden burst.
        Submits concurrent requests simultaneously to stress queue and concurrency limiters,
        recording offered, submitted, accepted, rejected, successful, and failed counts.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: BURST (Source={source}, Offered={num_requests}, run_id={effective_run_id})...")
        results = []
        tracker = ConcurrencyTracker(max_concurrency=10, max_queue=20)

        def _worker(idx: int, admitted: bool, t_submit: float):
            bq = BENCHMARK_QUESTIONS[idx % len(BENCHMARK_QUESTIONS)]
            req_id = f"burst_{source}_{idx+1:03d}"

            if not admitted:
                # Task rejected by queue backpressure before admission
                res = PipelineResult(
                    request_id=req_id,
                    scenario="burst",
                    source=source,
                    start_time=time.time(),
                    first_token_ms=None,
                    total_ms=0.5,
                    total_wall_ms=0.5,
                    retrieval_ms=0.0,
                    generation_ms=0.0,
                    verification_ms=0.0,
                    processing_ms=0.5,
                    queue_wait_ms=0.0,
                    queue_depth=tracker.max_queue,
                    admission_queue_depth=tracker.max_queue,
                    concurrency=tracker.max_concurrency,
                    status="rate_limited",
                    retries=0,
                    tokens_in=max(1, len(bq.question.split())),
                    tokens_out=0,
                    is_simulated=(source in ("stand-in", "standin")),
                    retrieval_setting="setting_b",
                    degradation_reason="queue_capacity_breached_backpressure",
                    answer_grade="rate_limited",
                    answer="Request rejected due to bounded queue capacity backpressure.",
                    run_id=effective_run_id
                )
                self.logger.log_result(res)
                return res

            wait_ms, q_depth, in_flight = tracker.start_task(t_submit)
            try:
                res = self.pipeline.run_request(
                    query=bq.question,
                    request_id=req_id,
                    scenario="burst",
                    source=source,
                    retrieval_setting="setting_b",
                    expected_negative=bq.expected_negative,
                    run_id=effective_run_id,
                    question_id=bq.id,
                    ground_truth_key_facts=bq.ground_truth_key_facts,
                    queue_wait_ms=round(wait_ms, 1),
                    queue_depth=q_depth,
                    concurrency=in_flight,
                    sleeper=sleeper
                )
                res.admission_queue_depth = q_depth
                self.logger.log_result(res)
                return res
            finally:
                tracker.finish_task(res.status if 'res' in locals() else "error")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(num_requests, 10)) as executor:
            submissions = [tracker.submit_task() for _ in range(num_requests)]
            futures = [
                executor.submit(_worker, i, adm, t_sub)
                for i, (adm, t_sub) in enumerate(submissions)
            ]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    results.append(res)
                    print(f"  -> [{res.request_id}] Status={res.status}, TTFT={res.first_token_ms}ms, Retries={res.retries}")
                except Exception as e:
                    print(f"  -> Burst worker error: {e}")

        self.last_burst_stats = tracker.stats()
        print(f"  [Burst Accounting] Offered={tracker.offered_count}, Submitted={tracker.submitted_count}, Accepted={tracker.accepted_count}, Rejected={tracker.rejected_count}, Success={tracker.successful_count}, Failed={tracker.failed_count}")
        return results

    def run_scenario_sustained_overload(
        self,
        num_requests: int = 30,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        sleeper: Optional[Any] = None
    ) -> list[PipelineResult]:
        """
        Scenario 3: Sustained overload.
        Continuous flood of requests arriving faster than the system can process,
        stressing bounded queue capacity and backpressure.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: SUSTAINED OVERLOAD (Source={source}, Requests={num_requests}, run_id={effective_run_id})...")
        results = []
        tracker = ConcurrencyTracker(max_concurrency=5, max_queue=15)

        def _worker(idx: int, admitted: bool, t_submit: float):
            bq = BENCHMARK_QUESTIONS[idx % len(BENCHMARK_QUESTIONS)]
            req_id = f"sustained_{source}_{idx+1:03d}"

            if not admitted:
                res = PipelineResult(
                    request_id=req_id,
                    scenario="sustained_overload",
                    source=source,
                    start_time=time.time(),
                    first_token_ms=None,
                    total_ms=0.5,
                    total_wall_ms=0.5,
                    retrieval_ms=0.0,
                    generation_ms=0.0,
                    verification_ms=0.0,
                    processing_ms=0.5,
                    queue_wait_ms=0.0,
                    queue_depth=tracker.max_queue,
                    admission_queue_depth=tracker.max_queue,
                    concurrency=tracker.max_concurrency,
                    status="rate_limited",
                    retries=0,
                    tokens_in=max(1, len(bq.question.split())),
                    tokens_out=0,
                    is_simulated=(source in ("stand-in", "standin")),
                    retrieval_setting="setting_b",
                    degradation_reason="queue_capacity_breached_backpressure",
                    answer_grade="rate_limited",
                    answer="Request rejected due to bounded queue capacity backpressure.",
                    run_id=effective_run_id
                )
                self.logger.log_result(res)
                return res

            wait_ms, q_depth, in_flight = tracker.start_task(t_submit)
            try:
                res = self.pipeline.run_request(
                    query=bq.question,
                    request_id=req_id,
                    scenario="sustained_overload",
                    source=source,
                    retrieval_setting="setting_b",
                    expected_negative=bq.expected_negative,
                    run_id=effective_run_id,
                    question_id=bq.id,
                    ground_truth_key_facts=bq.ground_truth_key_facts,
                    queue_wait_ms=round(wait_ms, 1),
                    queue_depth=q_depth,
                    concurrency=in_flight,
                    sleeper=sleeper
                )
                res.admission_queue_depth = q_depth
                self.logger.log_result(res)
                return res
            finally:
                tracker.finish_task(res.status if 'res' in locals() else "error")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(num_requests):
                adm, t_sub = tracker.submit_task()
                futures.append(executor.submit(_worker, i, adm, t_sub))
                time.sleep(0.01)  # rapid arrival rate exceeding processing capacity

            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    results.append(res)
                    print(f"  -> [{res.request_id}] Status={res.status}, Total={res.total_ms}ms")
                except Exception as e:
                    print(f"  -> Sustained worker error: {e}")

        self.last_sustained_stats = tracker.stats()
        print(f"  [Sustained Stats] Offered={tracker.offered_count}, Accepted={tracker.accepted_count}, Rejected={tracker.rejected_count}, PeakQueue={tracker._peak_queue_depth}, MaxConcurrency={tracker._max_concurrency}")
        return results

    def run_scenario_per_minute_halved(
        self,
        num_requests: int = 15,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        sleeper: Optional[Any] = None,
        pacing_delay: float = 1.0,
        baseline_rpm: Optional[int] = None
    ) -> list[PipelineResult]:
        """
        Scenario 4: Per-minute limit halved.
        Tests how the system throttles and queues when the provider cuts RPM quota by 50%.
        """
        from the_relay.config import SIMULATOR_BASELINE_RPM
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Running Scenario: PER-MINUTE LIMIT HALVED (Source={source}, run_id={effective_run_id})...")
        effective_rpm = None
        eff_baseline = None
        if source in ("stand-in", "standin"):
            client = self.pipeline.router.stand_in_client
            eff_baseline = baseline_rpm or client.baseline_rpm or SIMULATOR_BASELINE_RPM
            client.halve_rpm_limit(baseline=eff_baseline)
            effective_rpm = client.rpm_limit

        self.last_halved_stats = {
            "baseline_rpm": eff_baseline,
            "effective_rpm": effective_rpm,
            "requests_sent": num_requests
        }
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
                ground_truth_key_facts=bq.ground_truth_key_facts,
                queue_wait_ms=0.0,
                queue_depth=0,
                concurrency=1,
                sleeper=sleeper
            )
            self.logger.log_result(res)
            results.append(res)
            print(f"  -> [{req_id}] Status={res.status}, Retries={res.retries}, Total={res.total_ms}ms")
            if pacing_delay > 0:
                time.sleep(pacing_delay)

        return results

    def run_scenario_daily_budget_exhausted(
        self,
        num_requests: int = 15,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        pacing_delay: float = 0.2
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
                ground_truth_key_facts=bq.ground_truth_key_facts,
                queue_wait_ms=0.0,
                queue_depth=0,
                concurrency=1
            )
            self.logger.log_result(res)
            results.append(res)
            print(f"  -> [{req_id}] Status={res.status}, Notice: {res.answer[:80]}...")
            if pacing_delay > 0:
                time.sleep(pacing_delay)

        return results

    def run_retrieval_setting_benchmark(
        self,
        setting_key: str,
        source: str = "stand-in",
        run_id: Optional[str] = None,
        random_seed: Optional[int] = 42,
        sleeper: Optional[Any] = None,
        pacing_delay: Optional[float] = None
    ) -> list[PipelineResult]:
        """
        Run all 15 benchmark questions through a specific retrieval setting (for Table 3).
        Dedicated retrieval-quality benchmark mode:
        - Guarantees independent experiment context and fixed random seed.
        - Disables quota-triggered adaptive degradation (allow_degradation=False) so setting never degrades to A.
        - Isolates quota state so Setting A cannot contaminate B or C.
        """
        effective_run_id = run_id or "default_run"
        print(f"\n[TrafficGenerator] Evaluating Pure Retrieval-Quality Benchmark on {setting_key} (Source={source}, run_id={effective_run_id})...")

        eff_sleeper = sleeper
        eff_pacing = pacing_delay if pacing_delay is not None else (15.0 if source in ("groq", "real") else 0.0)

        # Isolate and reset simulator state for each setting so A does not contaminate B or C
        if source in ("stand-in", "standin"):
            client = self.pipeline.router.stand_in_client
            if random_seed is not None:
                client.set_seed(random_seed)
            if eff_sleeper is None and getattr(client, "fast_mode", False):
                eff_sleeper = lambda _: None
            ctx = client.isolated_context(rpm_limit=1000)
        else:
            from contextlib import nullcontext
            ctx = nullcontext()

        with ctx:
            results = []
            for i, bq in enumerate(BENCHMARK_QUESTIONS):
                if i > 0 and eff_pacing > 0:
                    time.sleep(eff_pacing)
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
                    ground_truth_key_facts=bq.ground_truth_key_facts,
                    queue_wait_ms=0.0,
                    queue_depth=0,
                    concurrency=1,
                    sleeper=eff_sleeper,
                    allow_degradation=False
                )
                # Guarantee no silent setting change during pure retrieval benchmark
                assert res.retrieval_setting == setting_key, (
                    f"Quality benchmark setting mutated unexpectedly: requested {setting_key}, got {res.retrieval_setting}"
                )
                self.logger.log_result(res)
                results.append(res)
            return results
