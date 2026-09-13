"""Console entry point: ``contextslim`` or ``python -m contextslim``.

Three jobs live here:

* ``contextslim`` with no arguments starts the MCP server on stdio. This is
  what Claude Desktop launches, so it must stay the default behaviour.
* ``contextslim install`` registers this server with Claude Desktop on macOS,
  Windows or Linux, so nobody has to find a config file, hand-edit JSON, or
  work out an absolute path to a virtual environment.
* ``contextslim --info`` prints the resolved configuration, for diagnostics.

The install command encodes the two mistakes that actually cost people time:
Claude Desktop rewrites its own config file when it exits (so an edit made
while it is running is silently discarded), and the interpreter path has to be
the one this package is installed into, not whatever ``python`` happens to
resolve to. Both are handled here rather than left to the reader.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

DEFAULT_SERVER_NAME = "contextslim"

#: Where each OS keeps Claude Desktop's configuration file.
_CONFIG_LOCATIONS = {
    "Darwin": ("Library", "Application Support", "Claude", "claude_desktop_config.json"),
    "Linux": (".config", "Claude", "claude_desktop_config.json"),
}

_QUIT_HELP = (
    "  macOS   - press Cmd+Q (closing the window is not enough)\n"
    "  Windows - right-click the Claude icon in the system tray and choose Quit\n"
    "  Linux   - close it from the tray or run: pkill -x claude"
)


# ---------------------------------------------------------------------------
# Locating Claude Desktop's config
# ---------------------------------------------------------------------------
def claude_config_path(system: Optional[str] = None, env: Optional[dict] = None) -> Path:
    """Return the path to ``claude_desktop_config.json`` for this OS.

    Windows uses %APPDATA%; macOS and Linux use fixed locations under the
    user's home directory. The file itself may not exist yet - that is fine,
    the installer creates it.
    """
    system = system or platform.system()
    env = os.environ if env is None else env

    if system == "Windows":
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"

    parts = _CONFIG_LOCATIONS.get(system, _CONFIG_LOCATIONS["Linux"])
    return Path.home().joinpath(*parts)


def _run_command(command: List[str]) -> Optional[str]:
    """Run a command and return its stdout, or None if it could not run."""
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        )
    except Exception:
        return None
    return finished.stdout


#: Process names for the Claude *Desktop* application, per OS. Deliberately
#: excludes a bare lowercase "claude": that is the Claude Code CLI, and
#: matching it would wrongly block every developer who has the CLI installed.
_DESKTOP_PROCESS_NAMES = {
    "Darwin": ("Claude",),
    "Linux": ("claude-desktop",),
}


def claude_is_running(
    system: Optional[str] = None, runner: Optional[Callable[[List[str]], Optional[str]]] = None
) -> Optional[bool]:
    """Is Claude Desktop running right now?

    Returns True, False, or None when it genuinely cannot be determined (for
    example if the process-listing tool is missing). None is treated as "warn
    but continue", because refusing to install over an unknown is worse than
    a warning.
    """
    system = system or platform.system()
    run = runner or _run_command

    if system == "Windows":
        output = run(["tasklist", "/FI", "IMAGENAME eq Claude.exe"])
        if output is None:
            return None
        return "claude.exe" in output.lower()

    for name in _DESKTOP_PROCESS_NAMES.get(system, _DESKTOP_PROCESS_NAMES["Linux"]):
        output = run(["pgrep", "-x", name])
        if output is None:
            return None
        if output.strip():
            return True
    return False


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------
def _load_config(path: Path) -> tuple[Optional[dict], Optional[str]]:
    """Return ``(data, error)``. An unreadable file is an error, not an empty dict."""
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return None, "Could not read " + str(path) + ": " + str(exc)
    if not text:
        return {}, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (
            "The existing config file is not valid JSON (" + str(exc) + "). "
            "Nothing was changed. Fix or delete the file, then run this again."
        )
    if not isinstance(data, dict):
        return None, "The existing config file does not contain a JSON object. Nothing was changed."
    return data, None


def _backup(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    backup_path = str(path) + ".backup"
    shutil.copy2(path, backup_path)
    return backup_path


def install_server(
    name: str = DEFAULT_SERVER_NAME,
    config_path: Optional[str] = None,
    python_executable: Optional[str] = None,
    system: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
    force: bool = False,
    running_check: Optional[Callable[[], Optional[bool]]] = None,
) -> dict:
    """Register this server in Claude Desktop's config file.

    Existing servers and every other key in the file are preserved; only this
    one entry is added or replaced, and the previous file is backed up first.
    """
    path = Path(config_path) if config_path else claude_config_path(system, env)
    check = running_check or (lambda: claude_is_running(system))
    running = check()

    if running and not force:
        return {
            "ok": False,
            "reason": "claude_running",
            "config_path": str(path),
            "message": (
                "Claude Desktop is running. It rewrites this config file when it exits, "
                "so an edit made now would be thrown away.\n\nQuit it completely, then "
                "run this again:\n" + _QUIT_HELP + "\n\n(Or re-run with --force to write "
                "anyway - not recommended.)"
            ),
        }

    data, error = _load_config(path)
    if error is not None:
        return {"ok": False, "reason": "unreadable_config", "config_path": str(path), "message": error}

    interpreter = python_executable or sys.executable
    entry = {"command": str(interpreter), "args": ["-m", "contextslim"]}
    servers = data.get("mcpServers") or {}
    action = "updated" if name in servers else "added"

    if dry_run:
        preview = dict(servers)
        preview[name] = entry
        return {
            "ok": True,
            "action": action,
            "dry_run": True,
            "config_path": str(path),
            "python": str(interpreter),
            "backup_path": None,
            "servers": sorted(preview),
            "warning_running": bool(running),
            "message": "Dry run - nothing was written.",
        }

    backup_path = _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reuse the dict read above: a file containing "mcpServers": null would
    # defeat setdefault and blow up on assignment.
    servers[name] = entry
    data["mcpServers"] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "action": action,
        "dry_run": False,
        "config_path": str(path),
        "python": str(interpreter),
        "backup_path": backup_path,
        "servers": sorted(data["mcpServers"]),
        "warning_running": bool(running),
        "message": "ContextSlim is registered with Claude Desktop.",
    }


def uninstall_server(
    name: str = DEFAULT_SERVER_NAME,
    config_path: Optional[str] = None,
    system: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
    force: bool = False,
    running_check: Optional[Callable[[], Optional[bool]]] = None,
) -> dict:
    """Remove this server from Claude Desktop's config, leaving others alone."""
    path = Path(config_path) if config_path else claude_config_path(system, env)
    check = running_check or (lambda: claude_is_running(system))
    running = check()

    if running and not force:
        return {
            "ok": False,
            "reason": "claude_running",
            "config_path": str(path),
            "message": "Claude Desktop is running - quit it first.\n" + _QUIT_HELP,
        }

    data, error = _load_config(path)
    if error is not None:
        return {"ok": False, "reason": "unreadable_config", "config_path": str(path), "message": error}

    servers = data.get("mcpServers") or {}
    if name not in servers:
        return {
            "ok": True,
            "action": "absent",
            "config_path": str(path),
            "servers": sorted(servers),
            "message": "'" + name + "' was not registered. Nothing to do.",
        }

    if dry_run:
        remaining = [key for key in servers if key != name]
        return {
            "ok": True,
            "action": "removed",
            "dry_run": True,
            "config_path": str(path),
            "backup_path": None,
            "servers": sorted(remaining),
            "message": "Dry run - nothing was written.",
        }

    backup_path = _backup(path)
    del data["mcpServers"][name]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "action": "removed",
        "dry_run": False,
        "config_path": str(path),
        "backup_path": backup_path,
        "servers": sorted(data["mcpServers"]),
        "message": "'" + name + "' removed from Claude Desktop.",
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def format_result(result: dict) -> str:
    """Render an install/uninstall result as something a human wants to read."""
    lines = [result.get("message", "")]

    detail_keys = (("config_path", "config "), ("python", "python "), ("backup_path", "backup "))
    details = []
    for key, label in detail_keys:
        value = result.get(key)
        if value:
            details.append("  " + label + ": " + str(value))
    if result.get("servers"):
        details.append("  servers: " + ", ".join(result["servers"]))
    if details:
        lines.append("")
        lines.extend(details)

    if result.get("ok") and not result.get("dry_run") and result.get("action") != "absent":
        lines.append("")
        if result.get("warning_running"):
            lines.append(
                "WARNING: Claude Desktop was running, so it may overwrite this. "
                "Quit it and run the command again if the tools do not appear."
            )
            lines.append("")
        lines.append("Next step: quit Claude Desktop completely, then reopen it.")
        lines.append(_QUIT_HELP)
        lines.append("")
        lines.append(
            'Then ask Claude: "check my context health with a token count of 94000"'
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextslim",
        description="ContextSlim AI - MCP server for session-state compression.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "install", "uninstall"],
        help=(
            "serve (default): start the MCP server on stdio. "
            "install: register this server with Claude Desktop. "
            "uninstall: remove it again."
        ),
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
    parser.add_argument(
        "--name",
        default=DEFAULT_SERVER_NAME,
        help="Name to register the server under (default: contextslim).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to claude_desktop_config.json. Found automatically if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what install/uninstall would change, without writing anything.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even if Claude Desktop is running (it may overwrite the change).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.info:
        import asyncio

        from .service import get_service

        report = asyncio.run(get_service().health())
        print(json.dumps(report, indent=2))
        return 0

    if args.command in ("install", "uninstall"):
        worker = install_server if args.command == "install" else uninstall_server
        result = worker(
            name=args.name,
            config_path=args.config,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(format_result(result))
        return 0 if result["ok"] else 1

    from .server import run

    if args.transport == "stdio":
        run(transport="stdio")
    else:
        run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
