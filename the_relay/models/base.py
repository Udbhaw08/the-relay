"""Base model client interfaces and telemetry structures."""
import time
from abc import ABC, abstractmethod
from typing import Generator, Optional
from pydantic import BaseModel

class ModelResponse(BaseModel):
    text: str
    first_token_ms: Optional[float] = None
    total_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    actual_input_tokens: Optional[int] = None
    actual_output_tokens: Optional[int] = None
    actual_total_tokens: Optional[int] = None
    estimated_input_tokens: Optional[int] = None
    estimated_output_tokens: Optional[int] = None
    estimated_total_tokens: Optional[int] = None
    is_simulated: bool = False
    provider: str
    model_name: str
    status: str = "ok"  # ok, rate_limited, timeout, error
    error_message: Optional[str] = None
    rate_limit_headers: dict[str, str] = {}
    retries_used: int = 0

class BaseModelClient(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> ModelResponse:
        """Synchronously generate text and track latency telemetry."""
        pass

    @abstractmethod
    def stream_generate(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000
    ) -> Generator[str, None, ModelResponse]:
        """Stream generated tokens piece-by-piece and return final telemetry upon completion."""
        pass

