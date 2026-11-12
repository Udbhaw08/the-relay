"""Router providing unified access to GroqCloud API and the Calibrated Stand-In."""
from typing import Optional
from the_relay.models.base import BaseModelClient
from the_relay.models.groq_client import GroqClient
from the_relay.models.stand_in import StandInModelClient
from the_relay.config import LLM_PROVIDER
from the_relay.pipeline.resilience import LocalQuotaLimiter

class ModelRouter:
    """
    Router directing traffic to either the Groq client (the only real provider)
    or the stand-in simulator (only for explicitly selected offline tests).
    """
    def __init__(
        self,
        provider: Optional[str] = None,
        limiter: Optional[LocalQuotaLimiter] = None
    ):
        self.provider = (provider or LLM_PROVIDER).lower()
        self.limiter = limiter if limiter is not None else LocalQuotaLimiter()
        self._groq_client: Optional[GroqClient] = None
        self._stand_in_client: Optional[StandInModelClient] = None

    @property
    def groq_client(self) -> GroqClient:
        if self._groq_client is None:
            self._groq_client = GroqClient(limiter=self.limiter)
        return self._groq_client

    @property
    def real_client(self) -> BaseModelClient:
        """Alias for backward compatibility - returns the sole real provider (Groq)."""
        return self.groq_client

    @property
    def stand_in_client(self) -> StandInModelClient:
        if self._stand_in_client is None:
            self._stand_in_client = StandInModelClient()
        return self._stand_in_client

    def get_client(self, source: Optional[str] = None) -> BaseModelClient:
        """
        Return the appropriate client based on the requested source.
        - 'groq', 'real', 'live' -> GroqClient (the ONLY real LLM provider)
        - 'stand-in', 'standin' -> StandInModelClient (strictly for offline tests)
        - If source is None:
            - If LLM_PROVIDER is 'standin' or 'stand-in', returns stand-in client.
            - Otherwise returns GroqClient.
        """
        # If router is explicitly in standin mode and source is not explicitly forcing real/groq:
        if self.provider in ("standin", "stand-in") and source not in ("real", "live", "groq"):
            return self.stand_in_client

        if source in ("stand-in", "standin"):
            return self.stand_in_client

        # Default to Groq as the sole real provider
        return self.groq_client
