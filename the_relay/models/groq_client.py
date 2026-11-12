"""GroqCloud API client with streaming telemetry, structured usage, and typed rate-limit tracking."""
import re
import time
from typing import Any, Generator, Optional
import groq
from groq import Groq
from the_relay.models.base import BaseModelClient, ModelResponse
from the_relay.config import GROQ_API_KEY, GROQ_MODEL, REQUEST_TIMEOUT_SECONDS, GROQ_BASE_URL, RETIRED_MODELS

def sanitize_error(error_message: str, api_key: Optional[str] = None) -> str:
    """Sanitize error messages to ensure API keys, auth tokens, and sensitive headers are never leaked."""
    if not error_message:
        return "Unknown error"
    msg = str(error_message)
    if api_key and api_key in msg:
        msg = msg.replace(api_key, "[REDACTED_API_KEY]")
    # Redact any gsk_ pattern
    msg = re.sub(r"gsk_[a-zA-Z0-9_-]+", "[REDACTED_API_KEY]", msg)
    # Redact Bearer tokens
    msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", msg, flags=re.IGNORECASE)
    # Redact authorization headers
    msg = re.sub(
        r"('authorization'|\"authorization\"|authorization)\s*:\s*('[^']+'|\"[^\"]+\")",
        "authorization: '[REDACTED]'",
        msg,
        flags=re.IGNORECASE
    )
    return msg

def extract_rate_limit_headers(headers: Any) -> dict[str, str]:
    """Extract relevant rate limit headers from response headers in a safe, structured format."""
    if not headers:
        return {}
    relevant_keys = [
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
        "x-request-id"
    ]
    header_map = {}
    if hasattr(headers, "items"):
        for k, v in headers.items():
            header_map[str(k).lower()] = str(v)
    elif isinstance(headers, dict):
        for k, v in headers.items():
            header_map[str(k).lower()] = str(v)

    extracted = {}
    for k in relevant_keys:
        val = header_map.get(k)
        if val is not None:
            extracted[k] = str(val)
    return extracted

class GroqClient(BaseModelClient):
    """
    GroqCloud API client implementing the BaseModelClient interface.
    Supports non-stream generation and streaming generation, structured usage metadata,
    and typed error handling with rate-limit headers.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        base_url: Optional[str] = None,
        client: Optional[Any] = None
    ):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = GROQ_API_KEY

        if not self.api_key or not self.api_key.strip():
            raise ValueError(
                "GROQ_API_KEY is not set or is empty. Please set GROQ_API_KEY in your environment or .env file."
            )
        
        target_base_url = base_url or GROQ_BASE_URL
        if target_base_url and ("x.ai" in target_base_url.lower() or "grok" in target_base_url.lower()):
            raise ValueError(
                "Invalid provider endpoint: xAI Grok is NOT supported. GroqCloud (api.groq.com) is the required target provider."
            )
            
        target_model = model_name if model_name is not None else GROQ_MODEL
        if not target_model or not target_model.strip():
            raise ValueError(
                "GROQ_MODEL is not set or is empty. Please set GROQ_MODEL in your environment or .env file."
            )
        if target_model in RETIRED_MODELS:
            raise ValueError(
                f"Configured model '{target_model}' is decommissioned on GroqCloud Free/Developer tier. "
                f"Please update GROQ_MODEL to a supported production model such as 'openai/gpt-oss-20b'."
            )

        self.model_name = target_model
        self.timeout = timeout
        self.base_url = target_base_url

        if client is not None:
            self.client = client
        else:
            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": self.timeout
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = Groq(**kwargs)

    def generate(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000
    ) -> ModelResponse:
        """Call Groq API synchronously while capturing latency metrics and usage."""
        start_time = time.perf_counter()
        tokens_in = max(1, len(prompt.split()) * 4 // 3)
        tokens_out = 0

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            raw_response = self.client.chat.completions.with_raw_response.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            completion = raw_response.parse()
            end_time = time.perf_counter()
            total_ms = max(0.1, (end_time - start_time) * 1000.0)

            content = ""
            if completion.choices and len(completion.choices) > 0:
                choice = completion.choices[0]
                if hasattr(choice, "message") and choice.message:
                    content = getattr(choice.message, "content", "") or ""

            # Extract structured usage metadata if provided upstream
            actual_in: Optional[int] = None
            actual_out: Optional[int] = None
            actual_tot: Optional[int] = None
            if hasattr(completion, "usage") and completion.usage:
                actual_in = getattr(completion.usage, "prompt_tokens", None)
                actual_out = getattr(completion.usage, "completion_tokens", None)
                actual_tot = getattr(completion.usage, "total_tokens", None)

            est_in = max(1, len(prompt.split()) * 4 // 3)
            est_out = max(1, len(content.split()) * 4 // 3)
            est_tot = est_in + est_out

            tokens_in = actual_in if actual_in is not None else est_in
            tokens_out = actual_out if actual_out is not None else est_out

            # Extract rate limit headers from HTTP response
            rate_limit_headers = extract_rate_limit_headers(raw_response.headers)
            
            # If server returned request-id or groq id, record it
            if hasattr(completion, "id") and completion.id:
                rate_limit_headers["id"] = str(completion.id)

            return ModelResponse(
                text=content,
                first_token_ms=round(total_ms, 1),
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                actual_input_tokens=actual_in,
                actual_output_tokens=actual_out,
                actual_total_tokens=actual_tot,
                estimated_input_tokens=est_in,
                estimated_output_tokens=est_out,
                estimated_total_tokens=est_tot,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="ok",
                rate_limit_headers=rate_limit_headers
            )

        except groq.RateLimitError as rle:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            resp = getattr(rle, "response", None)
            headers = extract_rate_limit_headers(getattr(resp, "headers", None)) if resp else {}
            headers["status_code"] = "429"
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=est_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="rate_limited",
                error_message=sanitize_error(str(rle), self.api_key),
                rate_limit_headers=headers
            )
        except groq.AuthenticationError as ae:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            resp = getattr(ae, "response", None)
            headers = extract_rate_limit_headers(getattr(resp, "headers", None)) if resp else {}
            headers["status_code"] = "401"
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=est_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="error",
                error_message="Groq authentication failed: Invalid API key or unauthorized.",
                rate_limit_headers=headers
            )
        except groq.APITimeoutError as te:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=est_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="timeout",
                error_message=sanitize_error(f"Groq request timed out: {te}", self.api_key)
            )
        except (groq.APIConnectionError, groq.InternalServerError, groq.APIStatusError) as ase:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            resp_headers = getattr(ase, "response", None)
            headers = extract_rate_limit_headers(getattr(resp_headers, "headers", None)) if resp_headers else {}
            status_code = getattr(ase, "status_code", 500)
            headers["status_code"] = str(status_code)
            status = "rate_limited" if status_code == 429 else "error"
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=est_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status=status,
                error_message=sanitize_error(str(ase), self.api_key),
                rate_limit_headers=headers
            )
        except Exception as e:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text="",
                first_token_ms=None,
                total_ms=round(total_ms, 1),
                tokens_in=est_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="error",
                error_message=sanitize_error(str(e), self.api_key)
            )

    def stream_generate(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000
    ) -> Generator[str, None, ModelResponse]:
        """Stream chunks from Groq, tracking TTFT and returning final ModelResponse."""
        start_time = time.perf_counter()
        first_token_ms = 0.0
        full_text = ""
        tokens_in = max(1, len(prompt.split()) * 4 // 3)
        tokens_out = 0
        rate_limit_headers: dict[str, str] = {}

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
                stream=True,
                stream_options={"include_usage": True}
            )
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    chunk_text = delta.content if hasattr(delta, "content") and delta.content else ""
                    if chunk_text:
                        if first_token_ms == 0.0:
                            first_token_ms = max(0.1, (time.perf_counter() - start_time) * 1000.0)
                        full_text += chunk_text
                        yield chunk_text
                
                # Check for usage in chunk (from stream_options)
                if hasattr(chunk, "usage") and chunk.usage:
                    actual_tokens_in = getattr(chunk.usage, "prompt_tokens", None)
                    actual_tokens_out = getattr(chunk.usage, "completion_tokens", None)
                    if actual_tokens_in is not None:
                        tokens_in = actual_tokens_in
                    if actual_tokens_out is not None:
                        tokens_out = actual_tokens_out
                if hasattr(chunk, "id") and chunk.id:
                    rate_limit_headers["id"] = str(chunk.id)

            end_time = time.perf_counter()
            total_ms = max(0.1, (end_time - start_time) * 1000.0)

            final_first_token_ms: Optional[float] = None
            if first_token_ms > 0.0 and full_text.strip():
                final_first_token_ms = round(first_token_ms, 1)
                total_ms = max(first_token_ms, total_ms)

            est_in = max(1, len(prompt.split()) * 4 // 3)
            est_out = max(1, len(full_text.split()) * 4 // 3) if full_text.strip() else 0
            est_tot = est_in + est_out

            actual_tot = (tokens_in + tokens_out) if (tokens_in > 0 and tokens_out > 0) else None

            return ModelResponse(
                text=full_text,
                first_token_ms=final_first_token_ms,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=tokens_out if tokens_out > 0 else est_out,
                actual_input_tokens=tokens_in if hasattr(chunk, "usage") and chunk.usage else None,
                actual_output_tokens=tokens_out if hasattr(chunk, "usage") and chunk.usage else None,
                actual_total_tokens=actual_tot if hasattr(chunk, "usage") and chunk.usage else None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=est_out,
                estimated_total_tokens=est_tot,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="ok",
                rate_limit_headers=rate_limit_headers
            )
        except groq.RateLimitError as rle:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            resp = getattr(rle, "response", None)
            headers = extract_rate_limit_headers(getattr(resp, "headers", None)) if resp else {}
            headers["status_code"] = "429"
            ttft = round(first_token_ms, 1) if (first_token_ms > 0.0 and full_text.strip()) else None
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text=full_text,
                first_token_ms=ttft,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="rate_limited",
                error_message=sanitize_error(str(rle), self.api_key),
                rate_limit_headers=headers
            )
        except groq.AuthenticationError as ae:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            resp = getattr(ae, "response", None)
            headers = extract_rate_limit_headers(getattr(resp, "headers", None)) if resp else {}
            headers["status_code"] = "401"
            ttft = round(first_token_ms, 1) if (first_token_ms > 0.0 and full_text.strip()) else None
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text=full_text,
                first_token_ms=ttft,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="error",
                error_message="Groq authentication failed: Invalid API key or unauthorized.",
                rate_limit_headers=headers
            )
        except groq.APITimeoutError as te:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            ttft = round(first_token_ms, 1) if (first_token_ms > 0.0 and full_text.strip()) else None
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text=full_text,
                first_token_ms=ttft,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="timeout",
                error_message=sanitize_error(f"Groq request timed out: {te}", self.api_key)
            )
        except Exception as e:
            end_time = time.perf_counter()
            total_ms = (end_time - start_time) * 1000.0
            ttft = round(first_token_ms, 1) if (first_token_ms > 0.0 and full_text.strip()) else None
            est_in = max(1, len(prompt.split()) * 4 // 3)
            return ModelResponse(
                text=full_text,
                first_token_ms=ttft,
                total_ms=round(total_ms, 1),
                tokens_in=tokens_in,
                tokens_out=0,
                actual_input_tokens=None,
                actual_output_tokens=None,
                actual_total_tokens=None,
                estimated_input_tokens=est_in,
                estimated_output_tokens=0,
                estimated_total_tokens=est_in,
                is_simulated=False,
                provider="groq",
                model_name=self.model_name,
                status="error",
                error_message=sanitize_error(str(e), self.api_key)
            )
