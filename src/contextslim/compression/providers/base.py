"""Provider contract for deep-mode compression.

Deep mode is one prompt and one JSON reply, so the model vendor is an
implementation detail. Everything vendor-specific lives behind this interface:
`DeepCompressor` owns the prompt, chunking, JSON parsing, rate limiting and
fallback, and never imports a vendor SDK.

That keeps ContextSlim provider-agnostic — switching vendors is one
environment variable, not a rewrite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class DeepProvider(ABC):
    """A model backend that turns a prompt into raw text."""

    #: Short identifier used in config and reported in results.
    name: str = "provider"
    #: Environment variable holding this provider's key, named in error messages.
    env_var: str = "API_KEY"

    def __init__(self, settings, client=None) -> None:
        self.settings = settings
        self._client = client

    # -- capability ------------------------------------------------------
    @property
    @abstractmethod
    def api_key(self) -> Optional[str]:
        """The configured key for this provider, if any."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The model id this provider will call."""

    @property
    def available(self) -> bool:
        """True when a usable key is configured."""
        key = self.api_key
        return bool(key and key.strip())

    @property
    def unavailable_reason(self) -> str:
        return (
            self.env_var
            + " is not set, so deep mode via "
            + self.name
            + " is unavailable."
        )

    # -- work ------------------------------------------------------------
    @abstractmethod
    async def generate(self, system: str, user: str) -> str:
        """Send the prompt and return the model's raw text response."""

    def describe(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "available": self.available,
            "key_env_var": self.env_var,
        }
