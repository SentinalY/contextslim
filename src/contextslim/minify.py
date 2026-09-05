"""Raw text minifier - Layer 1, zero latency and zero cost.

A regex pass that normalises whitespace, drops empty lines, and strips
redundant characters before anything else touches the text. Typical saving is
5-15% of tokens for free, on top of whatever the compressor achieves later.

Fenced code blocks are copied through untouched: collapsing whitespace inside
Python or YAML would corrupt the very decisions a capsule exists to preserve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

from .tokens import count_tokens, reduction_pct

# Fenced code blocks (``` or ~~~), non-greedy, spanning lines.
_CODE_FENCE_RE = re.compile(r"(?:^|\n)(?:```|~~~).*?(?:```|~~~)(?=\n|$)", re.DOTALL)

# Zero-width and BOM characters that cost tokens and carry no meaning.
_INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿]")

# Non-breaking and exotic spaces -> plain space.
_ODD_SPACE_RE = re.compile(r"[  -   　]")

# Runs of spaces/tabs that are not at the start of a line.
_INNER_SPACE_RE = re.compile(r"(?<=\S)[ \t]{2,}")

# A line made only of separator characters, e.g. "-----" or "======".
_SEPARATOR_LINE_RE = re.compile(r"^\s*(?:[-=_*~#]\s*){4,}$")

# Four or more repeats of the same punctuation mark.
_REPEAT_PUNCT_RE = re.compile(r"([!?.,;:\-–—])\1{3,}")

# Three or more consecutive newlines.
_BLANK_RUN_RE = re.compile(r"\n{3,}")


@dataclass
class MinifyResult:
    """Before/after numbers for a single minify pass."""

    text: str
    original_chars: int
    minified_chars: int
    original_tokens: int
    minified_tokens: int
    tokens_saved: int
    reduction_pct: float

    def as_dict(self) -> dict:
        data = asdict(self)
        data.pop("text")
        return data


def _minify_prose(chunk: str, aggressive: bool) -> str:
    """Minify a non-code segment."""
    text = chunk.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE_RE.sub("", text)
    text = _ODD_SPACE_RE.sub(" ", text)
    text = _REPEAT_PUNCT_RE.sub(r"\1\1\1", text)

    lines: list[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        if _SEPARATOR_LINE_RE.match(line):
            continue  # decorative rule: pure token waste
        line = _INNER_SPACE_RE.sub(" ", line)
        if aggressive and not line.strip():
            continue
        lines.append(line)

    text = "\n".join(lines)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text


def minify(text: Optional[str], aggressive: bool = False) -> str:
    """Return ``text`` with redundant characters removed.

    Args:
        text: Raw input. ``None`` or empty returns ``""``.
        aggressive: Also delete every blank line. Off by default because
            blank lines carry paragraph structure that helps the summariser
            split the text sensibly.
    """
    if not text:
        return ""

    out: list[str] = []
    cursor = 0
    for match in _CODE_FENCE_RE.finditer(text):
        out.append(_minify_prose(text[cursor : match.start()], aggressive))
        out.append(match.group(0))  # code block, verbatim
        cursor = match.end()
    out.append(_minify_prose(text[cursor:], aggressive))

    result = "".join(out)
    result = _BLANK_RUN_RE.sub("\n\n", result)
    return result.strip()


def minify_with_stats(
    text: Optional[str],
    aggressive: bool = False,
    encoding_name: str = "cl100k_base",
) -> MinifyResult:
    """Minify ``text`` and report how much it saved."""
    original = text or ""
    minified = minify(original, aggressive=aggressive)
    original_tokens = count_tokens(original, encoding_name)
    minified_tokens = count_tokens(minified, encoding_name)
    return MinifyResult(
        text=minified,
        original_chars=len(original),
        minified_chars=len(minified),
        original_tokens=original_tokens,
        minified_tokens=minified_tokens,
        tokens_saved=max(0, original_tokens - minified_tokens),
        reduction_pct=reduction_pct(original_tokens, minified_tokens),
    )
