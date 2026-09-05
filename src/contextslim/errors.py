"""Error types for ContextSlim.

Every MCP tool converts these into a structured ``{"ok": False, "error": ...}``
payload rather than letting an exception escape: a raised exception inside an
MCP tool is opaque to the calling client, which defeats the point of the
protocol layer.
"""

from __future__ import annotations


class ContextSlimError(Exception):
    """Base class for all errors raised inside ContextSlim."""

    code = "contextslim_error"


class CapsuleNotFoundError(ContextSlimError):
    """Requested session_id does not exist in the capsule store."""

    code = "capsule_not_found"


class InvalidInputError(ContextSlimError):
    """Caller supplied input that cannot be processed."""

    code = "invalid_input"


class CompressionError(ContextSlimError):
    """A compressor failed to produce a usable capsule."""

    code = "compression_failed"


class IngestionError(ContextSlimError):
    """A source file could not be converted to Markdown."""

    code = "ingestion_failed"


class RateLimitedError(ContextSlimError):
    """Deep-mode call rejected by the local rate limiter."""

    code = "rate_limited"
