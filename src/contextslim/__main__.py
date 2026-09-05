"""Console entry point: ``contextslim`` or ``python -m contextslim``."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contextslim",
        description="ContextSlim AI - MCP server for session-state compression.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "http", "sse"],
        help="MCP transport. Claude Desktop and Cursor use stdio (default).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for http/sse transport.")
    parser.add_argument("--port", type=int, default=8765, help="Port for http/sse transport.")
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print resolved configuration and exit (no server started).",
    )
    args = parser.parse_args(argv)

    if args.info:
        import asyncio
        import json

        from .service import get_service

        report = asyncio.run(get_service().health())
        print(json.dumps(report, indent=2))
        return 0

    from .server import run

    if args.transport == "stdio":
        run(transport="stdio")
    else:
        run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
