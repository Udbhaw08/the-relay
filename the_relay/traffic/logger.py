"""Thread-safe CSV logger for results.csv following exact schema specifications."""
import csv
import threading
from pathlib import Path
from typing import Optional
from the_relay.config import RESULTS_PATH
from the_relay.pipeline.orchestrator import PipelineResult

CSV_COLUMNS = [
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
    "answer_grade",
    "run_id",
    "requested_retrieval_setting",
    "degradation_reason",
    "actual_input_tokens",
    "actual_output_tokens",
    "actual_total_tokens",
    "estimated_input_tokens",
    "estimated_output_tokens",
    "estimated_total_tokens",
    "is_simulated",
    "retrieval_ms",
    "generation_ms",
    "verification_ms",
    "queue_wait_ms",
    "processing_ms",
    "total_wall_ms",
    "queue_depth",
    "admission_queue_depth",
    "concurrency",
    "scheduled_offset_s",
    "dispatch_offset_s",
    "dispatch_lateness_ms",
    "queue_arrival_time",
    "processing_start_time"
]

LEGACY_CSV_COLUMNS = [
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

class ResultsLogger:
    def __init__(self, file_path: Path = RESULTS_PATH, run_id: Optional[str] = None):
        self.file_path = file_path
        self.run_id = run_id
        self._lock = threading.Lock()
        self._columns = CSV_COLUMNS
        self._init_csv()

    def _init_csv(self):
        """Initialize the CSV file with headers if it does not exist, or detect existing headers."""
        with self._lock:
            if not self.file_path.exists() or self.file_path.stat().st_size == 0:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    writer.writeheader()
                self._columns = CSV_COLUMNS
            else:
                # Read existing header to match exactly and avoid header corruption
                with open(self.file_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        self._columns = [c.strip() for c in first_line.split(",") if c.strip()]
                    else:
                        self._columns = CSV_COLUMNS

    def log_result(self, res: PipelineResult):
        """Append a single request result to results.csv."""
        first_token_val = (
            f"{res.first_token_ms:.1f}"
            if (res.first_token_ms is not None and res.status == "ok" and res.tokens_out > 0)
            else ""
        )
        effective_run_id = getattr(res, "run_id", None) or self.run_id or "default_run"
        requested_setting = getattr(res, "requested_retrieval_setting", None) or res.retrieval_setting

        row = {
            "request_id": res.request_id,
            "scenario": res.scenario,
            "source": res.source,
            "start_time": f"{res.start_time:.3f}",
            "first_token_ms": first_token_val,
            "total_ms": f"{res.total_ms:.1f}",
            "status": res.status,
            "retries": res.retries,
            "tokens_in": res.tokens_in,
            "tokens_out": res.tokens_out,
            "retrieval_setting": res.retrieval_setting,
            "answer_grade": res.answer_grade,
            "run_id": effective_run_id,
            "requested_retrieval_setting": requested_setting,
            "degradation_reason": getattr(res, "degradation_reason", "") or "",
            "actual_input_tokens": "" if res.actual_input_tokens is None else res.actual_input_tokens,
            "actual_output_tokens": "" if res.actual_output_tokens is None else res.actual_output_tokens,
            "actual_total_tokens": "" if res.actual_total_tokens is None else res.actual_total_tokens,
            "estimated_input_tokens": "" if res.estimated_input_tokens is None else res.estimated_input_tokens,
            "estimated_output_tokens": "" if res.estimated_output_tokens is None else res.estimated_output_tokens,
            "estimated_total_tokens": "" if res.estimated_total_tokens is None else res.estimated_total_tokens,
            "is_simulated": getattr(res, "is_simulated", False),
            "retrieval_ms": f"{res.retrieval_ms:.1f}" if res.retrieval_ms is not None else "",
            "generation_ms": f"{res.generation_ms:.1f}" if res.generation_ms is not None else "",
            "verification_ms": f"{res.verification_ms:.1f}" if res.verification_ms is not None else "",
            "queue_wait_ms": f"{res.queue_wait_ms:.1f}" if res.queue_wait_ms is not None else "",
            "processing_ms": f"{res.processing_ms:.1f}" if res.processing_ms is not None else "",
            "total_wall_ms": f"{res.total_wall_ms:.1f}" if res.total_wall_ms is not None else "",
            "queue_depth": res.queue_depth if res.queue_depth is not None else "",
            "admission_queue_depth": getattr(res, "admission_queue_depth", "") if getattr(res, "admission_queue_depth", None) is not None else "",
            "concurrency": res.concurrency if res.concurrency is not None else "",
            "scheduled_offset_s": f"{res.scheduled_offset_s:.3f}" if getattr(res, "scheduled_offset_s", None) is not None else "",
            "dispatch_offset_s": f"{res.dispatch_offset_s:.3f}" if getattr(res, "dispatch_offset_s", None) is not None else "",
            "dispatch_lateness_ms": f"{res.dispatch_lateness_ms:.1f}" if getattr(res, "dispatch_lateness_ms", None) is not None else "",
            "queue_arrival_time": f"{res.queue_arrival_time:.3f}" if getattr(res, "queue_arrival_time", None) is not None else "",
            "processing_start_time": f"{res.processing_start_time:.3f}" if getattr(res, "processing_start_time", None) is not None else ""
        }
        with self._lock:
            with open(self.file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._columns, extrasaction="ignore")
                writer.writerow(row)
