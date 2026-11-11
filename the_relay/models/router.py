"""Router providing unified access to Real LLM clients and the Calibrated Stand-In."""
from typing import Optional
from the_relay.models.base import BaseModelClient, ModelResponse
from the_relay.models.gemini_client import GeminiClient
from the_relay.models.stand_in import StandInModelClient
from the_relay.config import PRIMARY_PROVIDER

class ModelRouter:
    def __init__(self, primary_provider: str = PRIMARY_PROVIDER):
        self.primary_provider = primary_provider
        self._real_client: Optional[BaseModelClient] = None
        self._stand_in_client: Optional[StandInModelClient] = None

    @property
    def real_client(self) -> BaseModelClient:
        if self._real_client is None:
            self._real_client = GeminiClient()
        return self._real_client

    @property
    def stand_in_client(self) -> StandInModelClient:
        if self._stand_in_client is None:
            self._stand_in_client = StandInModelClient()
        return self._stand_in_client

    def get_client(self, source: str = "real") -> BaseModelClient:
        """Return the appropriate client based on the source flag ('real' or 'stand-in')."""
        if source in ("real", "live"):
            return self.real_client
        return self.stand_in_client

