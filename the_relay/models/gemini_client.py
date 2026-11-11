"""Gemini API client with streaming telemetry and rate-limit tracking."""
import os
import time
from typing import Generator, Optional
from google import genai
from google.genai import types
from google.genai import errors
from the_relay.models.base import BaseModelClient, ModelResponse
from the_relay.config import GEMINI_API_KEY, REQUEST_TIMEOUT_SECONDS

class GeminiClient(BaseModelClient):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set. Please set it in .env")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name

    def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> ModelResponse:
        """Call Gemini synchronously while capturing latency metrics."""
        start_time = time.perf_counter()
        first_token_ms = 0.0
        full_text = ""
        tokens_in = max(1, len(prompt.split()) * 4 // 3)
        tokens_out = 0

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            system_instruction=system_prompt if system_prompt else None,
            temperature=0.2,
        )

        try:
            # We use stream even in generate() so we can precisely capture first_token_ms
            stream = self.client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
                config=config
            )
            for chunk in stream:
                if first_token_ms == 0.0:
                    first_token_ms = (time.perf_counter() - start_time) * 1000.0
                chunk_text = chunk.text or ""
                full_text += chunk_text

            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            if first_token_ms == 0.0:
                first_token_ms = total_ms

            tokens_out = max(1, len(full_text.split()) * 4 // 3)

            return ModelResponse(
                text=full_text,
                first_token_ms=round(first_token_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                provider="gemini",
                model_name=self.model_name,
                status="ok"
            )

        except errors.ClientError as ce:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            status = "rate_limited" if ce.code == 429 else "error"
            return ModelResponse(
                text="",
                first_token_ms=round(total_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                provider="gemini",
                model_name=self.model_name,
                status=status,
                error_message=str(ce),
                rate_limit_headers={"status_code": str(ce.code)}
            )
        except Exception as e:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            return ModelResponse(
                text="",
                first_token_ms=round(total_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                provider="gemini",
                model_name=self.model_name,
                status="error",
                error_message=str(e)
            )

    def stream_generate(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000
    ) -> Generator[str, None, ModelResponse]:
        """Stream chunks to the caller, then return the ModelResponse summary."""
        start_time = time.perf_counter()
        first_token_ms = 0.0
        full_text = ""
        tokens_in = max(1, len(prompt.split()) * 4 // 3)

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            system_instruction=system_prompt if system_prompt else None,
            temperature=0.2,
        )

        try:
            stream = self.client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
                config=config
            )
            for chunk in stream:
                if first_token_ms == 0.0:
                    first_token_ms = (time.perf_counter() - start_time) * 1000.0
                chunk_text = chunk.text or ""
                full_text += chunk_text
                yield chunk_text

            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            tokens_out = max(1, len(full_text.split()) * 4 // 3)

            return ModelResponse(
                text=full_text,
                first_token_ms=round(first_token_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                provider="gemini",
                model_name=self.model_name,
                status="ok"
            )
        except Exception as e:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            return ModelResponse(
                text=full_text,
                first_token_ms=round(first_token_ms or total_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                provider="gemini",
                model_name=self.model_name,
                status="error",
                error_message=str(e)
            )

