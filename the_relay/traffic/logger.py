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
    "requested_retrieval_setting"
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
            "requested_retrieval_setting": requested_setting
        }
        with self._lock:
            with open(self.file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._columns, extrasaction="ignore")
                writer.writerow(row)
