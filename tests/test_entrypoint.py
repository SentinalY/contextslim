"""CLI entry point and server construction.

This is the code Claude Desktop actually launches, so it gets tested too.
"""

from __future__ import annotations

import json
import logging

import pytest

from contextslim.__main__ import main
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
