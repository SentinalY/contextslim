"""Approximate token counting.

The risk register is explicit about this: tiktoken uses OpenAI's tokenizer,
so counts for Claude are an approximation. That is fine — these numbers drive
analytics and health thresholds, not billing, and every surface labels them
"approximate".

tiktoken downloads its BPE vocabulary on first use. On a machine with no
network that download fails, so the counter degrades to a character-ratio
estimate instead of taking the whole server down with it.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Empirically ~4 characters per token for English prose and code. Used only
# when tiktoken is unavailable.
_CHARS_PER_TOKEN = 4.0


class TokenCounter:
    """Counts tokens with tiktoken, falling back to a character estimate."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self.encoding_name = encoding_name
        self._encoding = None
        self._degraded = False
        self._load_attempted = False

    # -- internals ------------------------------------------------------
    def _load_encoding(self):
        if self._load_attempted:
            return self._encoding
        self._load_attempted = True
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding(self.encoding_name)
        except Exception as exc:  # network down, bad name, tiktoken missing
            self._degraded = True
            logger.warning(
                "tiktoken unavailable (%s); using character-ratio token estimate",
                exc.__class__.__name__,
            )
        return self._encoding

    # -- public API -----------------------------------------------------
    @property
    def is_degraded(self) -> bool:
        """True when counts come from the fallback estimator."""
        self._load_encoding()
        return self._degraded

    @property
    def method(self) -> str:
        return "character-estimate" if self.is_degraded else self.encoding_name

    def count(self, text: Optional[str]) -> int:
        """Return the approximate token count of ``text``."""
        if not text:
            return 0
        encoding = self._load_encoding()
        if encoding is None:
            return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))
        try:
            return len(encoding.encode(text, disallowed_special=()))
        except Exception:  # pragma: no cover - defensive
            return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))


@lru_cache(maxsize=4)
def get_counter(encoding_name: str = "cl100k_base") -> TokenCounter:
    """Return a cached counter for ``encoding_name``."""
    return TokenCounter(encoding_name)


def count_tokens(text: Optional[str], encoding_name: str = "cl100k_base") -> int:
    """Convenience wrapper around the cached :class:`TokenCounter`."""
    return get_counter(encoding_name).count(text)


def reduction_pct(raw_tokens: int, compressed_tokens: int) -> float:
    """Percentage of tokens removed, clamped to [0, 100] and rounded."""
    if raw_tokens <= 0:
        return 0.0
    pct = (raw_tokens - compressed_tokens) / raw_tokens * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def token_metrics(
    raw_tokens: int, compressed_tokens: int, encoding_name: str = "cl100k_base"
) -> dict:
    """The Token Metrics Display payload: raw -> compressed -> reduction%."""
    counter = get_counter(encoding_name)
    return {
        "raw_tokens": raw_tokens,
        "compressed_tokens": compressed_tokens,
        "tokens_saved": max(0, raw_tokens - compressed_tokens),
        "reduction_pct": reduction_pct(raw_tokens, compressed_tokens),
        "counting_method": counter.method,
        "note": "Token counts are approximate (tiktoken/GPT tokenizer).",
    }
