"""Claude Haiku backend for deep mode.

This is the provider named in the ContextSlim product document. It is kept
alongside the Gemini backend so the vendor choice stays a configuration
decision rather than something baked into the compressor.
"""

from __future__ import annotations

from typing import Optional

from .base import DeepProvider


class AnthropicProvider(DeepProvider):
    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    @property
    def api_key(self) -> Optional[str]:
        return self.settings.anthropic_api_key

    @property
    def model(self) -> str:
        return self.settings.anthropic_model

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def generate(self, system: str, user: str) -> str:
        client = self._get_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=self.settings.deep_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        )
