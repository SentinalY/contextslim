"""Gemini Flash backend for deep mode (default provider).

Uses Google's `google-genai` SDK. The SDK is imported lazily so the package
is only needed by people who actually run deep mode with Gemini.

`response_mime_type="application/json"` asks Gemini for raw JSON, which
removes the usual "here is your JSON:" preamble. `DeepCompressor` still
tolerates fenced or chatty output, so this is an optimisation, not a
dependency.
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import DeepProvider


class GeminiProvider(DeepProvider):
    name = "gemini"
    env_var = "GEMINI_API_KEY"

    @property
    def api_key(self) -> Optional[str]:
        return self.settings.gemini_api_key

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    def _get_client(self):
        if self._client is None:
            from google import genai

            # The SDK logs an advisory notice about automatic function calling
            # on every generate_content call. ContextSlim never uses function
            # calling, so the notice is pure noise in the MCP log stream.
            logging.getLogger("google_genai.models").setLevel(logging.ERROR)
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate(self, system: str, user: str) -> str:
        from google.genai import types

        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=self.settings.deep_max_tokens,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""
