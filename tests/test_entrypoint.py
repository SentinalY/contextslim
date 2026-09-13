"""CLI entry point and server construction.

This is the code Claude Desktop actually launches, so it gets tested too.
"""

from __future__ import annotations

import json
import logging
import sys

import pytest

from contextslim import __main__ as cli
from contextslim.__main__ import (
    claude_config_path,
    claude_is_running,
    format_result,
    install_server,
    main,
    uninstall_server,
)
from contextslim.server import build_server, configure_logging, mcp


def test_info_flag_prints_configuration(capsys):
    exit_code = main(["--info"])
    assert exit_code == 0

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["capsules_stored"] == 0
    assert "database_path" in report
    assert report["modes"].keys() >= {"slim", "deep"}


def test_info_reports_the_configured_database_path(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXTSLIM_HOME", str(tmp_path / "custom"))
    from contextslim.config import reset_settings_cache
    from contextslim.service import reset_service

    reset_settings_cache()
    reset_service()

    main(["--info"])
    report = json.loads(capsys.readouterr().out)
    assert str(tmp_path / "custom") in report["database_path"]
    reset_service()


def test_unknown_transport_is_rejected():
    with pytest.raises(SystemExit):
        main(["--transport", "carrier-pigeon"])


def test_build_server_returns_the_configured_mcp_instance():
    server = build_server()
    assert server is mcp
    assert server.name == "contextslim"


def test_build_server_creates_runtime_directories():
    from contextslim.config import get_settings

    build_server()
    settings = get_settings()
    assert settings.data_home.is_dir()
    assert settings.exports_path.is_dir()


def test_logging_goes_to_stderr_not_stdout():
    """stdout is the MCP JSON-RPC channel; a stray log line corrupts it."""
    try:
        configure_logging("DEBUG")
        handlers = logging.getLogger().handlers
        assert handlers
        streams = [getattr(h, "stream", None) for h in handlers]
        assert all(getattr(s, "name", "") != "<stdout>" for s in streams)
    finally:
        configure_logging("WARNING")  # don't leave the suite in DEBUG


def test_server_instructions_tell_the_model_when_to_act():
    assert "check_context_health" in mcp.instructions
    assert "extract_session_state" in mcp.instructions


# ===========================================================================
# contextslim install / uninstall
#
# This is the command that saves every new user from finding a config file,
# hand-editing JSON and getting an absolute path right, so it is tested on
# all three operating systems without touching a real Claude installation.
# ===========================================================================

NOT_RUNNING = lambda: False  # noqa: E731 - injected check, kept inline for readability
RUNNING = lambda: True  # noqa: E731


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- locating the config ---------------------------------------------------


def test_config_path_on_macos():
    path = claude_config_path(system="Darwin")
    assert path.parts[-4:] == (
        "Library",
        "Application Support",
        "Claude",
        "claude_desktop_config.json",
    )
    assert path.is_absolute()


def test_config_path_on_windows_uses_appdata():
    path = claude_config_path(system="Windows", env={"APPDATA": "C:/Users/x/AppData/Roaming"})
    assert str(path).replace("\\", "/").endswith(
        "AppData/Roaming/Claude/claude_desktop_config.json"
    )


def test_config_path_on_windows_without_appdata_falls_back():
    path = claude_config_path(system="Windows", env={})
    assert "Roaming" in str(path) and path.name == "claude_desktop_config.json"


def test_config_path_on_linux():
    path = claude_config_path(system="Linux", env={})
    assert str(path).endswith(".config/Claude/claude_desktop_config.json")


def test_unknown_os_falls_back_to_linux_layout():
    assert claude_config_path(system="Plan9", env={}) == claude_config_path(
        system="Linux", env={}
    )


# --- detecting a running app ----------------------------------------------


def test_running_detection_on_windows():
    assert claude_is_running("Windows", lambda cmd: "Claude.exe  1234 Console") is True
    assert claude_is_running("Windows", lambda cmd: "INFO: No tasks are running") is False


def test_running_detection_on_unix():
    assert claude_is_running("Darwin", lambda cmd: "4821\n") is True
    assert claude_is_running("Darwin", lambda cmd: "") is False


def test_running_detection_returns_none_when_it_cannot_tell():
    """A missing pgrep must not be reported as 'not running'."""
    assert claude_is_running("Darwin", lambda cmd: None) is None


def test_claude_code_cli_is_not_mistaken_for_claude_desktop():
    """Regression: the CLI's process is lowercase 'claude'.

    Matching it blocked installation for anyone with Claude Code installed -
    which is most of this project's users. Only the desktop app counts.
    """

    def only_the_cli_is_running(command):
        return "4821\n" if command[-1] == "claude" else ""

    assert claude_is_running("Darwin", only_the_cli_is_running) is False
    assert claude_is_running("Linux", only_the_cli_is_running) is False


def test_linux_looks_for_the_desktop_process_name():
    seen = []

    def record(command):
        seen.append(command[-1])
        return ""

    claude_is_running("Linux", record)
    assert seen == ["claude-desktop"]
    assert "claude" not in seen


# --- install ---------------------------------------------------------------


def test_install_creates_the_config_when_absent(tmp_path):
    target = tmp_path / "nested" / "claude_desktop_config.json"
    result = install_server(config_path=str(target), running_check=NOT_RUNNING)

    assert result["ok"] is True
    assert result["action"] == "added"
    assert target.exists()

    entry = read_json(target)["mcpServers"]["contextslim"]
    assert entry["args"] == ["-m", "contextslim"]
    assert entry["command"] == sys.executable  # the venv this is installed into


def test_install_uses_an_explicit_interpreter_when_given(tmp_path):
    target = tmp_path / "config.json"
    install_server(
        config_path=str(target),
        python_executable="C:/py/.venv/Scripts/python.exe",
        running_check=NOT_RUNNING,
    )
    entry = read_json(target)["mcpServers"]["contextslim"]
    assert entry["command"] == "C:/py/.venv/Scripts/python.exe"


def test_install_preserves_other_servers_and_other_keys(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "theme": "dark",
                "windowState": {"width": 900},
                "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}},
            }
        ),
        encoding="utf-8",
    )

    result = install_server(config_path=str(target), running_check=NOT_RUNNING)
    data = read_json(target)

    assert result["ok"] is True
    assert data["theme"] == "dark"
    assert data["windowState"] == {"width": 900}
    assert data["mcpServers"]["filesystem"]["command"] == "npx"
    assert "contextslim" in data["mcpServers"]
    assert result["servers"] == ["contextslim", "filesystem"]


def test_install_backs_up_the_previous_config(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    result = install_server(config_path=str(target), running_check=NOT_RUNNING)

    backup = tmp_path / "config.json.backup"
    assert backup.exists()
    assert read_json(backup) == {"theme": "dark"}
    assert result["backup_path"] == str(backup)


def test_reinstall_reports_update_not_add(tmp_path):
    target = tmp_path / "config.json"
    install_server(config_path=str(target), running_check=NOT_RUNNING)
    again = install_server(config_path=str(target), running_check=NOT_RUNNING)
    assert again["action"] == "updated"
    assert len(read_json(target)["mcpServers"]) == 1  # not duplicated


def test_install_handles_null_mcpservers(tmp_path):
    """A config with "mcpServers": null must not crash the installer."""
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"mcpServers": None}), encoding="utf-8")

    result = install_server(config_path=str(target), running_check=NOT_RUNNING)
    assert result["ok"] is True
    assert "contextslim" in read_json(target)["mcpServers"]


def test_custom_server_name(tmp_path):
    target = tmp_path / "config.json"
    install_server(config_path=str(target), name="slim-dev", running_check=NOT_RUNNING)
    assert "slim-dev" in read_json(target)["mcpServers"]


# --- install: refusals -----------------------------------------------------


def test_install_refuses_while_claude_is_running(tmp_path):
    """The lesson that cost the most time: the app overwrites its own config."""
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    result = install_server(config_path=str(target), running_check=RUNNING)

    assert result["ok"] is False
    assert result["reason"] == "claude_running"
    assert "quit" in result["message"].lower()
    assert read_json(target) == {"mcpServers": {}}  # untouched
    assert not (tmp_path / "config.json.backup").exists()


def test_force_writes_even_while_running_but_warns(tmp_path):
    target = tmp_path / "config.json"
    result = install_server(config_path=str(target), running_check=RUNNING, force=True)

    assert result["ok"] is True
    assert result["warning_running"] is True
    assert "contextslim" in read_json(target)["mcpServers"]
    assert "WARNING" in format_result(result)


def test_unknown_running_state_does_not_block(tmp_path):
    """None means 'could not tell' - warn, but do not refuse to work."""
    target = tmp_path / "config.json"
    result = install_server(config_path=str(target), running_check=lambda: None)
    assert result["ok"] is True


def test_install_refuses_to_touch_invalid_json(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{ this is not json", encoding="utf-8")

    result = install_server(config_path=str(target), running_check=NOT_RUNNING)

    assert result["ok"] is False
    assert result["reason"] == "unreadable_config"
    assert "not valid JSON" in result["message"]
    assert target.read_text(encoding="utf-8") == "{ this is not json"  # untouched


def test_install_refuses_a_non_object_config(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    result = install_server(config_path=str(target), running_check=NOT_RUNNING)
    assert result["ok"] is False


def test_empty_file_is_treated_as_empty_config(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("   \n", encoding="utf-8")
    result = install_server(config_path=str(target), running_check=NOT_RUNNING)
    assert result["ok"] is True
    assert "contextslim" in read_json(target)["mcpServers"]


def test_dry_run_changes_nothing(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    result = install_server(config_path=str(target), dry_run=True, running_check=NOT_RUNNING)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["servers"] == ["contextslim"]  # what it *would* be
    assert read_json(target) == {"mcpServers": {}}  # what it still is


# --- uninstall -------------------------------------------------------------


def test_uninstall_removes_only_our_entry(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps({"theme": "dark", "mcpServers": {"filesystem": {"command": "npx"}}}),
        encoding="utf-8",
    )
    install_server(config_path=str(target), running_check=NOT_RUNNING)

    result = uninstall_server(config_path=str(target), running_check=NOT_RUNNING)
    data = read_json(target)

    assert result["ok"] is True
    assert result["action"] == "removed"
    assert "contextslim" not in data["mcpServers"]
    assert data["mcpServers"]["filesystem"]["command"] == "npx"
    assert data["theme"] == "dark"


def test_uninstall_when_not_installed_is_not_an_error(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    result = uninstall_server(config_path=str(target), running_check=NOT_RUNNING)
    assert result["ok"] is True
    assert result["action"] == "absent"
    assert not (tmp_path / "config.json.backup").exists()


def test_uninstall_refuses_while_running(tmp_path):
    target = tmp_path / "config.json"
    install_server(config_path=str(target), running_check=NOT_RUNNING)
    result = uninstall_server(config_path=str(target), running_check=RUNNING)
    assert result["ok"] is False
    assert "contextslim" in read_json(target)["mcpServers"]


# --- the CLI wrapper -------------------------------------------------------


def test_cli_install_prints_next_steps_and_exits_zero(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "claude_is_running", lambda *a, **k: False)
    target = tmp_path / "config.json"

    exit_code = main(["install", "--config", str(target)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert target.exists()
    assert "quit Claude Desktop" in output
    assert "94000" in output  # the verification prompt to try


def test_cli_install_exits_nonzero_when_it_refuses(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "claude_is_running", lambda *a, **k: True)
    target = tmp_path / "config.json"

    exit_code = main(["install", "--config", str(target)])

    assert exit_code == 1
    assert not target.exists()
    assert "running" in capsys.readouterr().out.lower()


def test_cli_uninstall_round_trip(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "claude_is_running", lambda *a, **k: False)
    target = tmp_path / "config.json"

    main(["install", "--config", str(target)])
    assert "contextslim" in read_json(target)["mcpServers"]

    exit_code = main(["uninstall", "--config", str(target)])
    assert exit_code == 0
    assert "contextslim" not in read_json(target)["mcpServers"]


def test_cli_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "claude_is_running", lambda *a, **k: False)
    target = tmp_path / "config.json"

    exit_code = main(["install", "--config", str(target), "--dry-run"])

    assert exit_code == 0
    assert not target.exists()
    assert "Dry run" in capsys.readouterr().out


def test_serve_is_still_the_default_command():
    """Claude Desktop runs `python -m contextslim` with no arguments."""
    args = cli.build_parser().parse_args([])
    assert args.command == "serve"
    assert args.transport == "stdio"


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        main(["frobnicate"])
