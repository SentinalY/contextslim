"""ContextSlim AI - intelligent context optimization engine.

An MCP server that lets an AI compress and save its own working memory as
structured Context Capsules.

The package root stays deliberately light: importing :mod:`contextslim` must
not pull in the Anthropic client, sumy, or MarkItDown. Import the submodule
you need instead.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
