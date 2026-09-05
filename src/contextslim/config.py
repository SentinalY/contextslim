"""Environment-driven configuration.

Every tunable lives in an environment variable (optionally loaded from a
``.env`` file). No secret and no machine-specific path is ever written into
the repository, so a fresh clone on any laptop runs with the defaults and a
laptop with a key in ``.env`` unlocks deep mode automatically.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import default_data_home, ensure_dir, ensure_parent_dir, expand

# Project root = the directory containing pyproject.toml, two levels above
# this file (src/contextslim/config.py). Used only to find an optional .env.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Both are consulted, later entries winning: the project's own .env, then a
# .env in whatever directory the server was launched from.
_ENV_FILES = (_PROJECT_ROOT / ".env", Path(".env"))


class Settings(BaseSettings):
    """Runtime configuration for every ContextSlim component."""

    model_config = SettingsConfigDict(
        env_prefix="CONTEXTSLIM_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Lets callers (and tests) construct Settings(anthropic_api_key=...)
        # by field name even though the field also has an env alias.
        populate_by_name=True,
    )

    # --- Storage --------------------------------------------------------
    home: Optional[Path] = Field(
        default=None,
        description="Base data directory. Defaults to the OS user-data dir.",
    )
    db_path: Optional[Path] = Field(
        default=None, description="SQLite file. Defaults to <home>/contextslim.db"
    )
    export_dir: Optional[Path] = Field(
        default=None, description="Export target. Defaults to <home>/exports"
    )

    # --- Deep mode ------------------------------------------------------
    deep_provider: str = Field(
        default="gemini",
        description="Which model backend deep mode uses: 'gemini' or 'anthropic'.",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "CONTEXTSLIM_GEMINI_API_KEY"
        ),
        description="Google AI Studio key. Absent means deep mode falls back to slim.",
    )
    anthropic_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "ANTHROPIC_API_KEY", "CONTEXTSLIM_ANTHROPIC_API_KEY"
        ),
        description="Anthropic key. Absent means deep mode falls back to slim.",
    )
    gemini_model: str = "gemini-3.6-flash"
    anthropic_model: str = "claude-haiku-4-5"
    deep_max_tokens: int = 2000
    deep_rate_limit_per_minute: int = 20
    # Transient upstream failures (503 "high demand", 429 rate limits) are
    # retried before giving up and falling back to slim.
    deep_max_attempts: int = 3
    deep_retry_backoff_seconds: float = 1.0

    # --- Slim mode ------------------------------------------------------
    slim_sentences: int = 14

    # --- Token counting -------------------------------------------------
    token_encoding: str = "cl100k_base"

    # --- Context health thresholds --------------------------------------
    health_warning_tokens: int = 60_000
    health_critical_tokens: int = 80_000
    context_window_tokens: int = 200_000

    # --- Ingestion ------------------------------------------------------
    max_file_mb: int = 25

    # --- Logging --------------------------------------------------------
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @field_validator("slim_sentences")
    @classmethod
    def _positive_sentences(cls, value: int) -> int:
        if value < 1:
            raise ValueError("CONTEXTSLIM_SLIM_SENTENCES must be >= 1")
        return value

    @field_validator("max_file_mb", "deep_max_tokens")
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("value must be >= 1")
        return value

    @field_validator("deep_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        allowed = {"gemini", "anthropic"}
        lowered = (value or "gemini").strip().lower()
        if lowered not in allowed:
            raise ValueError(
                "CONTEXTSLIM_DEEP_PROVIDER must be one of " + ", ".join(sorted(allowed))
            )
        return lowered

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}")
        return upper

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> "Settings":
        if self.health_critical_tokens <= self.health_warning_tokens:
            raise ValueError(
                "CONTEXTSLIM_HEALTH_CRITICAL_TOKENS must be greater than "
                "CONTEXTSLIM_HEALTH_WARNING_TOKENS"
            )
        return self

    # ------------------------------------------------------------------
    # Resolved locations
    # ------------------------------------------------------------------
    @property
    def data_home(self) -> Path:
        return expand(self.home) if self.home else default_data_home()

    @property
    def database_path(self) -> Path:
        if self.db_path:
            return expand(self.db_path)
        return self.data_home / "contextslim.db"

    @property
    def exports_path(self) -> Path:
        if self.export_dir:
            return expand(self.export_dir)
        return self.data_home / "exports"

    @property
    def deep_api_key(self) -> Optional[str]:
        """The key belonging to the currently selected provider."""
        if self.deep_provider == "anthropic":
            return self.anthropic_api_key
        return self.gemini_api_key

    @property
    def deep_model(self) -> str:
        """The model id for the currently selected provider."""
        if self.deep_provider == "anthropic":
            return self.anthropic_model
        return self.gemini_model

    @property
    def deep_mode_available(self) -> bool:
        key = self.deep_api_key
        return bool(key and key.strip())

    def ensure_runtime_dirs(self) -> None:
        """Create every directory ContextSlim writes to. Safe to call often."""
        ensure_dir(self.data_home)
        ensure_parent_dir(self.database_path)
        ensure_dir(self.exports_path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings so new environment values are picked up.

    Used by the test suite, which points ContextSlim at a temporary
    directory rather than the real user-data directory.
    """
    get_settings.cache_clear()
