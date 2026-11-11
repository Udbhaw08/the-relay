"""Thread-safe CSV logger for results.csv following exact schema specifications."""
import csv
import threading
from pathlib import Path
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
    "answer_grade"
]

class ResultsLogger:
    def __init__(self, file_path: Path = RESULTS_PATH):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._init_csv()

    def _init_csv(self):
        """Initialize the CSV file with headers if it does not exist."""
        with self._lock:
            if not self.file_path.exists() or self.file_path.stat().st_size == 0:
                with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    writer.writeheader()

    def log_result(self, res: PipelineResult):
        """Append a single request result to results.csv."""
        row = {
            "request_id": res.request_id,
            "scenario": res.scenario,
            "source": res.source,
            "start_time": f"{res.start_time:.3f}",
            "first_token_ms": f"{res.first_token_ms:.1f}",
            "total_ms": f"{res.total_ms:.1f}",
            "status": res.status,
            "retries": res.retries,
            "tokens_in": res.tokens_in,
            "tokens_out": res.tokens_out,
            "retrieval_setting": res.retrieval_setting,
            "answer_grade": res.answer_grade
        }
        with self._lock:
            with open(self.file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writerow(row)

