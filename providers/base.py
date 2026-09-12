"""Abstract provider interface. All AI backends implement this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderResponse:
    text: str
    model: str
    usage: dict  # {prompt_tokens, completion_tokens, total_tokens}
    finish_reason: str  # stop | length | tool_call
    latency_ms: float
    tool_calls: list[dict] | None = None  # Native function calls from API


class BaseProvider(ABC):
    """Minimum contract every provider must fulfill."""

    def __init__(self, api_key: str, base_url: str, default_model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict]] = None,
    ) -> ProviderResponse:
        """Send prompt, get response. All providers follow this contract."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return available model IDs for this provider."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Provider", "").lower()