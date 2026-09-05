"""Shared test fixtures.

Two rules the whole suite obeys:

1. No test ever touches the real user-data directory. Every test points
   ContextSlim at a pytest ``tmp_path``.
2. No test needs the network. Deep mode is stubbed; slim mode, minification
   and token counting all work offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:  # allows `pytest` without an editable install
    sys.path.insert(0, str(SRC))

from contextslim.config import Settings, reset_settings_cache  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point every component at a throwaway directory with no API key."""
    monkeypatch.setenv("CONTEXTSLIM_HOME", str(tmp_path / "data"))
    for variable in (
        "ANTHROPIC_API_KEY",
        "CONTEXTSLIM_ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "CONTEXTSLIM_GEMINI_API_KEY",
        "CONTEXTSLIM_DEEP_PROVIDER",
        "CONTEXTSLIM_DB_PATH",
        "CONTEXTSLIM_EXPORT_DIR",
    ):
        monkeypatch.delenv(variable, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """A Settings instance rooted in the test's temporary directory."""
    return Settings(home=tmp_path / "data", _env_file=None)


@pytest.fixture
def sample_chat() -> str:
    """A realistic multi-turn engineering conversation used across tests."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "sample_chat.md"
    return fixture.read_text(encoding="utf-8")
