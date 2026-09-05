"""Shared contract for every compression backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..capsule import Capsule

#: The Compression Mode Selector's two options.
MODES = ("slim", "deep")

MODE_DESCRIPTIONS = {
    "slim": (
        "Free, offline, deterministic. Extractive summarisation (sumy/LSA) "
        "routes sentences into the six capsule sections. No API key, no cost, "
        "no network. Best for routine checkpoints."
    ),
    "deep": (
        "A model (Gemini Flash by default, Claude Haiku optionally) reads the "
        "whole session and writes the six sections abstractively. Higher "
        "fidelity, especially for decisions and constraints. Costs one small "
        "API call and needs the selected provider's API key; falls back to "
        "slim automatically when unavailable."
    ),
}


@dataclass
class CompressionResult:
    """What every compressor returns."""

    capsule: Capsule
    mode: str
    model: Optional[str] = None
    provider: Optional[str] = None
    fallback_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def used_fallback(self) -> bool:
        return self.fallback_reason is not None
