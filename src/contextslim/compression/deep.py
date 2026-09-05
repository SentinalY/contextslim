"""Deep mode - a model writes the six-section capsule.

Slim mode selects sentences; deep mode understands them. The model reads the
whole session and writes each section abstractively, which matters most for
DECISIONS (it can record what was rejected and why) and CONSTRAINTS.

The vendor is a configuration choice, not an architectural one. This module
owns the prompt, chunking, JSON parsing, rate limiting and fallback; a
:class:`~contextslim.compression.providers.base.DeepProvider` owns the API
call. Gemini Flash is the default; Claude Haiku (the provider named in the
product document) is one environment variable away.

Four safety rails, all from the product document's risk register:

* No API key, an API error, or unparseable output -> automatic slim fallback,
  with the reason reported instead of hidden.
* Transient upstream failures (503 "high demand", 429 rate limits) are retried
  with exponential backoff before falling back, because a busy model is not a
  reason to lose the capsule.
* A local rate limiter caps deep calls per minute so cost cannot run away.
* Very long sessions are compressed in chunks and merged, rather than being
  truncated or rejected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import List, Optional

from ..capsule import Capsule
from ..config import Settings, get_settings
from .base import CompressionResult
from .providers import DeepProvider, get_provider
from .slim import SlimCompressor

logger = logging.getLogger(__name__)

# Roughly 90k tokens of input per call; longer sessions are chunked.
_MAX_CHARS_PER_CALL = 350_000

_SYSTEM_PROMPT = """You are ContextSlim's session-state extractor.

You receive a raw AI chat session. You return a Context Capsule: a compact,
machine-readable save file that lets a brand-new chat resume the work with
full working memory and none of the token cost.

Return ONLY a JSON object with exactly these keys:

{
  "project":        "one or two sentences: what is being built and why",
  "completed":      ["work already finished, so it is never redone"],
  "decisions":      ["each choice made, with the rejected alternative when stated"],
  "current_state":  ["where the session stopped: what is in progress right now"],
  "next_objective": "the single next thing to do, stated as an action",
  "constraints":    ["rules that must not be violated: limits, bans, deadlines"]
}

Rules:
- Preserve every concrete value: names, versions, numbers, timeouts, paths, IDs.
- A decision must say what was chosen. Include the alternative if the session named one.
- Never invent facts. If a section has nothing, return an empty list or "".
- Write flat statements, not narration. No "the user asked", no "we discussed".
- Each list item is one self-contained sentence.
- Output JSON only. No prose, no markdown fences, no commentary."""


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` events per 60 seconds."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._events: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._events and now - self._events[0] > self.window:
            self._events.popleft()
        if len(self._events) >= self.limit:
            return False
        self._events.append(now)
        return True

    def reset(self) -> None:
        self._events.clear()


#: Upstream conditions that are worth retrying: the request was fine, the
#: service just could not serve it at that moment.
_RETRYABLE_CODES = (408, 429, 500, 502, 503, 504)
_RETRYABLE_CODE_RE = re.compile(r"\b(?:" + "|".join(str(c) for c in _RETRYABLE_CODES) + r")\b")
_RETRYABLE_MARKERS = (
    "unavailable",
    "overloaded",
    "high demand",
    "resource_exhausted",
    "rate limit",
    "timeout",
    "timed out",
    "temporarily",
    "try again",
    "connection reset",
)


def _is_retryable(exc: Exception) -> bool:
    """True when an exception looks transient rather than a real rejection.

    Checked vendor-neutrally: a status code attribute if the SDK exposes one,
    otherwise the message text. A bad key or an unknown model is NOT retried -
    repeating those just wastes the user's time.
    """
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code in _RETRYABLE_CODES

    text = str(exc).lower()
    if any(marker in text for marker in _RETRYABLE_MARKERS):
        return True
    return bool(_RETRYABLE_CODE_RE.search(text))


def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of a model response, fences and all."""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


class DeepCompressor:
    """Abstractive compression through the Anthropic API."""

    mode = "deep"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client=None,
        rate_limiter: Optional[RateLimiter] = None,
        provider: Optional[DeepProvider] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or get_provider(self.settings, client=client)
        self.rate_limiter = rate_limiter or RateLimiter(
            self.settings.deep_rate_limit_per_minute
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _fallback(self, text: str, reason: str, project, title) -> CompressionResult:
        logger.info("deep mode falling back to slim: %s", reason)
        result = SlimCompressor(self.settings).compress(text, project=project, title=title)
        result.fallback_reason = reason
        return result

    @staticmethod
    def _chunks(text: str, size: Optional[int] = None) -> List[str]:
        """Split on paragraph boundaries so no sentence is cut in half."""
        size = size or _MAX_CHARS_PER_CALL
        if len(text) <= size:
            return [text]
        chunks: List[str] = []
        remaining = text
        while len(remaining) > size:
            window = remaining[:size]
            split_at = window.rfind("\n\n")
            if split_at < size // 2:
                split_at = window.rfind("\n")
            if split_at < size // 2:
                split_at = size
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:]
        if remaining.strip():
            chunks.append(remaining)
        return chunks

    async def _call_with_retries(self, text: str, project, title, warnings: List[str]) -> Capsule:
        """Call the model, retrying transient failures with exponential backoff."""
        attempts = max(1, self.settings.deep_max_attempts)
        backoff = max(0.0, self.settings.deep_retry_backoff_seconds)

        for attempt in range(1, attempts + 1):
            try:
                return await self._call_model(text, project, title)
            except json.JSONDecodeError:
                raise  # bad output, not a transient failure
            except Exception as exc:
                if attempt >= attempts or not _is_retryable(exc):
                    raise
                delay = backoff * (2 ** (attempt - 1))
                warnings.append(
                    "Retry "
                    + str(attempt)
                    + "/"
                    + str(attempts - 1)
                    + " after a transient "
                    + self.provider.name
                    + " error ("
                    + exc.__class__.__name__
                    + ")."
                )
                logger.info("retrying deep-mode call in %.1fs: %s", delay, exc)
                if delay:
                    await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def _call_model(self, text: str, project, title) -> Capsule:
        context_bits = []
        if project:
            context_bits.append("Project: " + str(project))
        if title:
            context_bits.append("Session title: " + str(title))
        preamble = ("\n".join(context_bits) + "\n\n") if context_bits else ""

        raw = await self.provider.generate(
            _SYSTEM_PROMPT, preamble + "Compress this session:\n\n" + text
        )
        return Capsule(**_extract_json(raw))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def compress(
        self,
        text: str,
        project: Optional[str] = None,
        title: Optional[str] = None,
    ) -> CompressionResult:
        """Compress ``text`` with Haiku, falling back to slim on any failure."""
        if not (text or "").strip():
            return self._fallback(text, "Input was empty.", project, title)

        if not self.provider.available:
            return self._fallback(text, self.provider.unavailable_reason, project, title)

        if not self.rate_limiter.allow():
            return self._fallback(
                text,
                f"Deep-mode rate limit reached "
                f"({self.settings.deep_rate_limit_per_minute}/min).",
                project,
                title,
            )

        chunks = self._chunks(text)
        warnings: List[str] = []
        capsule: Optional[Capsule] = None

        try:
            for index, chunk in enumerate(chunks):
                part = await self._call_with_retries(chunk, project, title, warnings)
                capsule = part if capsule is None else capsule.merge(part)
            if len(chunks) > 1:
                warnings.append(
                    f"Session exceeded one model call; compressed in {len(chunks)} "
                    "chunks and merged."
                )
        except json.JSONDecodeError:
            return self._fallback(
                text, "Model returned output that was not valid JSON.", project, title
            )
        except Exception as exc:
            retries = len([w for w in warnings if w.startswith("Retry ")])
            attempted = " after " + str(retries + 1) + " attempts" if retries else ""
            return self._fallback(
                text,
                self.provider.name
                + " API call failed"
                + attempted
                + ": "
                + exc.__class__.__name__
                + ": "
                + str(exc),
                project,
                title,
            )

        if capsule is None or capsule.is_empty:
            return self._fallback(text, "Model returned an empty capsule.", project, title)

        return CompressionResult(
            capsule=capsule,
            mode=self.mode,
            model=self.provider.model,
            provider=self.provider.name,
            warnings=warnings,
        )
