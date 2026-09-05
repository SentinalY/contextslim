"""Deep-mode provider registry.

Selection is a single environment variable::

    CONTEXTSLIM_DEEP_PROVIDER=gemini      # default, free tier available
    CONTEXTSLIM_DEEP_PROVIDER=anthropic   # Claude Haiku, as per the product doc
"""

from __future__ import annotations

from typing import Optional

from ...errors import InvalidInputError
from .anthropic_provider import AnthropicProvider
from .base import DeepProvider
from .gemini_provider import GeminiProvider

PROVIDERS = {
    GeminiProvider.name: GeminiProvider,
    AnthropicProvider.name: AnthropicProvider,
}

PROVIDER_NAMES = tuple(PROVIDERS)


def get_provider(settings, client=None, name: Optional[str] = None) -> DeepProvider:
    """Build the configured provider. ``client`` is injected by tests."""
    chosen = (name or settings.deep_provider or "gemini").strip().lower()
    provider_class = PROVIDERS.get(chosen)
    if provider_class is None:
        raise InvalidInputError(
            "Unknown deep-mode provider '"
            + str(chosen)
            + "'. Valid providers: "
            + ", ".join(PROVIDER_NAMES)
            + "."
        )
    return provider_class(settings, client=client)


__all__ = [
    "DeepProvider",
    "GeminiProvider",
    "AnthropicProvider",
    "PROVIDERS",
    "PROVIDER_NAMES",
    "get_provider",
]
