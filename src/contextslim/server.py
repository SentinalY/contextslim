"""The MCP server - eight tools, exposed natively to any MCP client.

This module is deliberately thin. Every tool validates nothing and computes
nothing: it forwards to :class:`~contextslim.service.ContextSlimService` and
converts errors into a structured payload. An exception escaping a tool is
opaque to the client, so nothing is allowed to escape.

Tool docstrings are load-bearing. They are what the model reads when deciding
whether to call a tool, so they state *when* to use each one, not just what it
does - that is what makes the AI an active participant rather than a passive
executor.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastmcp import FastMCP

from .config import get_settings
from .errors import ContextSlimError
from .service import ContextSlimService, get_service

logger = logging.getLogger(__name__)

mcp: FastMCP = FastMCP(
    name="contextslim",
    instructions=(
        "ContextSlim manages session state so long conversations stay sharp and "
        "cheap. Call check_context_health() periodically during long sessions; "
        "when it reports WARNING or CRITICAL, offer to compress with "
        "extract_session_state() and tell the user the session id to restore in "
        "a fresh chat with load_capsule()."
    ),
)


def _service() -> ContextSlimService:
    return get_service()


def _error(exc: Exception) -> dict:
    """Convert an exception into a structured tool result."""
    if isinstance(exc, ContextSlimError):
        code = exc.code
        message = str(exc)
    else:  # unexpected: log the trace, return something the model can act on
        code = "internal_error"
        message = f"{exc.__class__.__name__}: {exc}"
        logger.exception("unhandled error in MCP tool")
    return {"ok": False, "error": {"code": code, "message": message}, "summary": message}


# ---------------------------------------------------------------------------
# 1. extract_session_state - the product
# ---------------------------------------------------------------------------
@mcp.tool
async def extract_session_state(
    chat_history: Optional[str] = None,
    mode: str = "slim",
    project: Optional[str] = None,
    title: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
) -> dict:
    """Compress a conversation into a stored Context Capsule and return its id.

    Use this when a session is getting long, before switching to a new chat, or
    whenever the user wants to save where they got to. Pass the conversation so
    far as `chat_history`.

    Modes:
      - "slim" (default): free, offline, deterministic extractive compression.
        Use for routine checkpoints.
      - "deep": a model (Gemini Flash by default, Claude Haiku optionally)
        rewrites the six sections abstractively. Higher fidelity for decisions
        and constraints; needs the selected provider's API key and falls back
        to slim automatically if it is missing or the call fails.

    `file_paths` additionally ingests PDF / DOCX / XLSX / CSV / TXT / MD
    documents into the capsule.

    Returns the session_id, before/after token metrics, and the capsule.
    """
    try:
        return await _service().extract_session_state(
            chat_history=chat_history,
            mode=mode,
            project=project,
            title=title,
            file_paths=file_paths,
        )
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 2. load_capsule
# ---------------------------------------------------------------------------
@mcp.tool
async def load_capsule(session_id: str) -> dict:
    """Restore a saved session by its 8-character id.

    Call this at the start of a fresh chat when the user says something like
    "load capsule A3F2K9B1" or "resume my last session". Read the returned
    `restore_prompt` as established context: it carries the project, the
    decisions already made, the constraints you must honour, and the next
    objective. Continue the work from there instead of asking the user to
    re-explain it.
    """
    try:
        return await _service().load_capsule(session_id)
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 3. list_capsules
# ---------------------------------------------------------------------------
@mcp.tool
async def list_capsules(limit: int = 20, project: Optional[str] = None) -> dict:
    """List saved sessions, newest first, so the user need not remember ids.

    Each entry carries the session id, title, mode, reduction percentage,
    timestamps and the next objective. Filter by `project` when the user is
    looking for one particular piece of work.
    """
    try:
        return await _service().list_capsules(limit=limit, project=project)
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 4. get_stats
# ---------------------------------------------------------------------------
@mcp.tool
async def get_stats() -> dict:
    """Report aggregate savings: sessions compressed, tokens processed and saved.

    Use when the user asks how much ContextSlim has saved them, or wants an
    overview of their compression history. Token counts are approximate.
    """
    try:
        return await _service().get_stats()
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 5. check_context_health
# ---------------------------------------------------------------------------
@mcp.tool
async def check_context_health(
    token_count: Optional[int] = None,
    chat_history: Optional[str] = None,
) -> dict:
    """Check whether this conversation has grown large enough to compress.

    Call this on your own initiative during long working sessions - roughly
    every 15-20 turns, or whenever you notice the history getting long. Pass
    your own estimate of the conversation size as `token_count`, or the text
    as `chat_history`.

    Returns HEALTHY, WARNING or CRITICAL. On WARNING, mention to the user that
    compressing soon would keep quality up and cost down. On CRITICAL,
    recommend compressing now with extract_session_state().
    """
    try:
        return _service().check_context_health(
            token_count=token_count, chat_history=chat_history
        )
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 6. update_capsule
# ---------------------------------------------------------------------------
@mcp.tool
async def update_capsule(
    session_id: str,
    chat_history: Optional[str] = None,
    mode: str = "slim",
    note: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
) -> dict:
    """Fold new progress into an existing capsule instead of creating a new one.

    Use this for the restore-work-compress loop: the user loaded a capsule,
    worked for a while, and wants the same capsule brought up to date. New
    decisions, completed work and constraints are merged with what was already
    there, the next objective is replaced, and the previous version is archived
    so nothing is lost.
    """
    try:
        return await _service().update_capsule(
            session_id=session_id,
            chat_history=chat_history,
            mode=mode,
            note=note,
            file_paths=file_paths,
        )
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 7. search_capsules
# ---------------------------------------------------------------------------
@mcp.tool
async def search_capsules(query: str, limit: int = 20) -> dict:
    """Find saved sessions by keyword across their capsule text.

    Use when the user describes a session by topic rather than by id - "the
    one about the auth rewrite", "where we picked the database". Returns
    matching capsules with a short excerpt around the match.
    """
    try:
        return await _service().search_capsules(query=query, limit=limit)
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# 8. export_capsule
# ---------------------------------------------------------------------------
@mcp.tool
async def export_capsule(
    session_id: str,
    format: str = "txt",
    destination: Optional[str] = None,
) -> dict:
    """Write a capsule to a file for use outside this client.

    Formats:
      - "txt": the restore prompt, ready to paste into ChatGPT, Gemini or any
        other assistant.
      - "json": the structured capsule plus metrics, for tooling and handoffs.

    Without `destination` the file is written to the configured export
    directory. Returns the path and the content.
    """
    try:
        return await _service().export_capsule(
            session_id=session_id, format=format, destination=destination
        )
    except Exception as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
def configure_logging(level: Optional[str] = None) -> None:
    """Send logs to stderr. stdout belongs to the MCP JSON-RPC channel."""
    import sys

    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def build_server() -> FastMCP:
    """Return the configured server, creating runtime directories first."""
    settings = get_settings()
    settings.ensure_runtime_dirs()
    configure_logging(settings.log_level)
    logger.info("ContextSlim MCP server ready (db: %s)", settings.database_path)
    return mcp


def run(transport: str = "stdio", **kwargs: Any) -> None:
    """Start the MCP server on the given transport."""
    build_server().run(transport=transport, **kwargs)
