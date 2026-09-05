"""Configuration and cross-platform path behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextslim import paths
from contextslim.config import Settings, get_settings, reset_settings_cache


def test_default_home_is_platform_specific_and_absolute():
    home = paths.default_data_home()
    assert home.is_absolute()
    assert home.name == "contextslim"


def test_home_can_be_overridden_by_env(tmp_path, monkeypatch):
    target = tmp_path / "custom-home"
    monkeypatch.setenv("CONTEXTSLIM_HOME", str(target))
    reset_settings_cache()
    settings = get_settings()
    assert settings.data_home == target.resolve()


def test_db_and_export_paths_derive_from_home(tmp_path):
    settings = Settings(home=tmp_path / "data", _env_file=None)
    assert settings.database_path == (tmp_path / "data" / "contextslim.db").resolve()
    assert settings.exports_path == (tmp_path / "data" / "exports").resolve()


def test_explicit_db_path_wins(tmp_path):
    explicit = tmp_path / "elsewhere" / "my.db"
    settings = Settings(home=tmp_path / "data", db_path=explicit, _env_file=None)
    assert settings.database_path == explicit.resolve()


def test_runtime_dirs_are_created_on_demand(tmp_path):
    settings = Settings(home=tmp_path / "fresh", _env_file=None)
    assert not (tmp_path / "fresh").exists()
    settings.ensure_runtime_dirs()
    assert settings.data_home.is_dir()
    assert settings.exports_path.is_dir()
    assert settings.database_path.parent.is_dir()


def test_tilde_and_env_vars_expand(monkeypatch, tmp_path):
    monkeypatch.setenv("CS_TEST_ROOT", str(tmp_path))
    expanded = paths.expand("$CS_TEST_ROOT/sub")
    assert expanded == (tmp_path / "sub").resolve()
    assert paths.expand("~").is_absolute()
    assert "~" not in str(paths.expand("~/x"))


def test_ensure_dir_is_idempotent(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    first = paths.ensure_dir(target)
    second = paths.ensure_dir(target)
    assert first == second == target.resolve()
    assert target.is_dir()


def test_deep_mode_unavailable_without_key(tmp_path):
    settings = Settings(home=tmp_path, _env_file=None)
    assert settings.deep_mode_available is False
    with_key = Settings(home=tmp_path, gemini_api_key="gm-test", _env_file=None)
    assert with_key.deep_mode_available is True


def test_blank_key_does_not_count_as_available(tmp_path):
    settings = Settings(home=tmp_path, gemini_api_key="   ", _env_file=None)
    assert settings.deep_mode_available is False


def test_gemini_is_the_default_provider(tmp_path):
    settings = Settings(home=tmp_path, _env_file=None)
    assert settings.deep_provider == "gemini"
    assert settings.deep_model == settings.gemini_model


def test_provider_selects_which_key_and_model_are_used(tmp_path):
    settings = Settings(
        home=tmp_path,
        deep_provider="anthropic",
        anthropic_api_key="sk-test",
        gemini_api_key=None,
        _env_file=None,
    )
    assert settings.deep_api_key == "sk-test"
    assert settings.deep_model == settings.anthropic_model
    assert settings.deep_mode_available is True


def test_wrong_providers_key_does_not_enable_deep_mode(tmp_path):
    """A Gemini key must not make the Anthropic path look available."""
    settings = Settings(
        home=tmp_path, deep_provider="anthropic", gemini_api_key="gm-test", _env_file=None
    )
    assert settings.deep_mode_available is False


def test_provider_name_is_normalised_and_validated(tmp_path):
    assert Settings(home=tmp_path, deep_provider="GEMINI", _env_file=None).deep_provider == "gemini"
    with pytest.raises(ValueError):
        Settings(home=tmp_path, deep_provider="openai", _env_file=None)


def test_gemini_key_accepts_google_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "from-google-env")
    reset_settings_cache()
    assert get_settings().gemini_api_key == "from-google-env"


def test_health_thresholds_must_be_ordered(tmp_path):
    with pytest.raises(ValueError):
        Settings(
            home=tmp_path,
            health_warning_tokens=90_000,
            health_critical_tokens=80_000,
            _env_file=None,
        )


def test_invalid_log_level_rejected(tmp_path):
    with pytest.raises(ValueError):
        Settings(home=tmp_path, log_level="LOUD", _env_file=None)


def test_slim_sentences_must_be_positive(tmp_path):
    with pytest.raises(ValueError):
        Settings(home=tmp_path, slim_sentences=0, _env_file=None)


def test_no_hardcoded_absolute_paths_in_source():
    """Guard the portability promise: no developer machine paths in the code."""
    src = Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for py_file in src.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for needle in ("/Users/", "C:\\\\Users", "/home/", "/Volumes/"):
            if needle in text:
                offenders.append((py_file.name, needle))
    assert offenders == []
