"""Deep mode: prompt shape, JSON parsing, rate limiting, chunking, fallbacks.

Deep mode is tested against a stub provider, so these tests cover the
compressor's own logic without touching any vendor SDK, the network, or a
paid API. Vendor wire formats are covered separately in test_providers.py.
"""

from __future__ import annotations

import json

import pytest

from contextslim.compression.deep import (
    DeepCompressor,
    RateLimiter,
    _extract_json,
    _is_retryable,
)
from contextslim.compression.providers.base import DeepProvider
from contextslim.config import Settings

VALID_PAYLOAD = {
    "project": "FastAPI authentication system for an internal portal",
    "completed": ["User model written", "Argon2id hashing wired"],
    "decisions": ["PostgreSQL over a new datastore", "RS256 over HS256"],
    "current_state": ["Refresh endpoint skeleton in place"],
    "next_objective": "Finish the JWT refresh endpoint with reuse detection",
    "constraints": ["No Redis until the Q4 datacentre migration"],
}


class StubProvider(DeepProvider):
    """Records prompts and returns canned replies."""

    name = "stub"
    env_var = "STUB_API_KEY"

    def __init__(self, settings, replies=None, error=None, available=True, fail_times=None):
        super().__init__(settings)
        self._replies = list(replies or [json.dumps(VALID_PAYLOAD)])
        self._error = error
        self._available = available
        # None = fail on every call; an int = fail only the first N calls.
        self._fail_times = fail_times
        self.calls = []

    @property
    def api_key(self):
        return "stub-key" if self._available else None

    @property
    def model(self) -> str:
        return "stub-model-1"

    async def generate(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if self._error is not None and (
            self._fail_times is None or len(self.calls) <= self._fail_times
        ):
            raise self._error
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


@pytest.fixture
def keyed_settings(tmp_path) -> Settings:
    # Zero backoff: retry logic is exercised without the suite sleeping.
    return Settings(
        home=tmp_path,
        gemini_api_key="gm-test-key",
        deep_retry_backoff_seconds=0.0,
        _env_file=None,
    )


def build(settings, **kwargs):
    provider = StubProvider(settings, **kwargs)
    return DeepCompressor(settings, provider=provider), provider


# --- JSON extraction -------------------------------------------------------


def test_extract_plain_json():
    assert _extract_json('{"project": "x"}') == {"project": "x"}


def test_extract_json_from_code_fence():
    assert _extract_json('```json\n{"project": "x"}\n```') == {"project": "x"}


def test_extract_json_with_surrounding_prose():
    assert _extract_json('Here you go:\n{"project": "x"}\nHope that helps.') == {"project": "x"}


def test_extract_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json at all")


# --- rate limiter ----------------------------------------------------------


def test_rate_limiter_allows_up_to_limit():
    limiter = RateLimiter(limit=3)
    assert [limiter.allow() for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_reset():
    limiter = RateLimiter(limit=1)
    assert limiter.allow() is True
    assert limiter.allow() is False
    limiter.reset()
    assert limiter.allow() is True


def test_rate_limiter_window_expiry(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("contextslim.compression.deep.time.monotonic", lambda: clock["now"])
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow() is True
    assert limiter.allow() is False
    clock["now"] += 61
    assert limiter.allow() is True


# --- happy path ------------------------------------------------------------


async def test_deep_mode_produces_capsule_from_model_output(keyed_settings, sample_chat):
    compressor, provider = build(keyed_settings)
    result = await compressor.compress(sample_chat)

    assert result.mode == "deep"
    assert result.used_fallback is False
    assert result.model == provider.model
    assert result.provider == "stub"
    assert result.capsule.decisions == VALID_PAYLOAD["decisions"]
    assert result.capsule.next_objective == VALID_PAYLOAD["next_objective"]


async def test_prompt_asks_for_all_six_sections(keyed_settings, sample_chat):
    compressor, provider = build(keyed_settings)
    await compressor.compress(sample_chat)

    system = provider.calls[0]["system"]
    for key in (
        "project",
        "completed",
        "decisions",
        "current_state",
        "next_objective",
        "constraints",
    ):
        assert key in system
    assert "JSON only" in system
    assert "FastAPI" in provider.calls[0]["user"]


async def test_project_and_title_are_passed_to_the_model(keyed_settings):
    compressor, provider = build(keyed_settings)
    await compressor.compress("some session text", project="Portal", title="Auth work")
    user = provider.calls[0]["user"]
    assert "Portal" in user and "Auth work" in user


async def test_fenced_model_output_is_accepted(keyed_settings):
    compressor, _ = build(
        keyed_settings, replies=["```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"]
    )
    result = await compressor.compress("text")
    assert result.mode == "deep"
    assert result.capsule.project.startswith("FastAPI")


# --- fallbacks -------------------------------------------------------------


async def test_missing_api_key_falls_back_to_slim(settings, sample_chat):
    compressor, provider = build(settings, available=False)
    result = await compressor.compress(sample_chat)

    assert result.mode == "slim"
    assert result.used_fallback is True
    assert "STUB_API_KEY" in result.fallback_reason
    assert provider.calls == []  # never reached the API
    assert result.capsule.decisions  # slim still produced a real capsule


async def test_real_default_provider_names_gemini_when_unconfigured(settings, sample_chat):
    """With no key at all, the message must name the variable to set."""
    result = await DeepCompressor(settings).compress(sample_chat)
    assert result.mode == "slim"
    assert "GEMINI_API_KEY" in result.fallback_reason
    assert "gemini" in result.fallback_reason


async def test_api_error_falls_back_to_slim(keyed_settings, sample_chat):
    compressor, _ = build(keyed_settings, error=RuntimeError("connection reset"))
    result = await compressor.compress(sample_chat)
    assert result.mode == "slim"
    assert "connection reset" in result.fallback_reason
    assert "stub" in result.fallback_reason
    assert not result.capsule.is_empty


async def test_invalid_json_falls_back_to_slim(keyed_settings, sample_chat):
    compressor, _ = build(keyed_settings, replies=["I'm afraid I can't do that."])
    result = await compressor.compress(sample_chat)
    assert result.mode == "slim"
    assert "valid JSON" in result.fallback_reason


async def test_empty_model_capsule_falls_back(keyed_settings, sample_chat):
    compressor, _ = build(keyed_settings, replies=[json.dumps({"project": "", "completed": []})])
    result = await compressor.compress(sample_chat)
    assert result.mode == "slim"
    assert "empty capsule" in result.fallback_reason


async def test_empty_input_falls_back(keyed_settings):
    compressor, _ = build(keyed_settings)
    result = await compressor.compress("   ")
    assert result.mode == "slim"
    assert "empty" in result.fallback_reason.lower()


async def test_rate_limit_falls_back_without_calling_the_api(tmp_path, sample_chat):
    settings = Settings(
        home=tmp_path,
        gemini_api_key="gm-test",
        deep_rate_limit_per_minute=1,
        _env_file=None,
    )
    compressor, provider = build(settings)

    first = await compressor.compress(sample_chat)
    second = await compressor.compress(sample_chat)

    assert first.mode == "deep"
    assert second.mode == "slim"
    assert "rate limit" in second.fallback_reason.lower()
    assert len(provider.calls) == 1


# --- retries ---------------------------------------------------------------


class FakeApiError(Exception):
    """Mimics an SDK error that carries an HTTP status code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def test_transient_conditions_are_retryable():
    assert _is_retryable(FakeApiError(503, "UNAVAILABLE")) is True
    assert _is_retryable(FakeApiError(429, "RESOURCE_EXHAUSTED")) is True
    assert _is_retryable(RuntimeError("503 This model is currently experiencing high demand")) is True
    assert _is_retryable(RuntimeError("The service is temporarily overloaded")) is True


def test_real_rejections_are_not_retryable():
    assert _is_retryable(FakeApiError(400, "API key not valid")) is False
    assert _is_retryable(FakeApiError(404, "model not found")) is False
    assert _is_retryable(RuntimeError("API key not valid. Please pass a valid key.")) is False


async def test_transient_failure_is_retried_then_succeeds(keyed_settings, sample_chat):
    """A busy model must not cost the user their deep capsule."""
    compressor, provider = build(
        keyed_settings,
        error=FakeApiError(503, "This model is currently experiencing high demand"),
        fail_times=1,
    )
    result = await compressor.compress(sample_chat)

    assert result.mode == "deep"
    assert result.used_fallback is False
    assert len(provider.calls) == 2
    assert any(w.startswith("Retry 1/") for w in result.warnings)


async def test_retries_are_capped_then_it_falls_back(keyed_settings, sample_chat):
    compressor, provider = build(
        keyed_settings, error=FakeApiError(503, "high demand"), fail_times=None
    )
    result = await compressor.compress(sample_chat)

    assert result.mode == "slim"
    assert len(provider.calls) == keyed_settings.deep_max_attempts
    assert "after 3 attempts" in result.fallback_reason
    assert not result.capsule.is_empty


async def test_permanent_errors_are_not_retried(keyed_settings, sample_chat):
    """Repeating a bad key or a dead model just wastes the user's time."""
    compressor, provider = build(
        keyed_settings, error=FakeApiError(404, "model not found"), fail_times=None
    )
    result = await compressor.compress(sample_chat)

    assert result.mode == "slim"
    assert len(provider.calls) == 1
    assert "after" not in result.fallback_reason


async def test_attempt_count_is_configurable(tmp_path, sample_chat):
    settings = Settings(
        home=tmp_path,
        gemini_api_key="gm-test",
        deep_max_attempts=5,
        deep_retry_backoff_seconds=0.0,
        _env_file=None,
    )
    compressor, provider = build(settings, error=FakeApiError(503, "busy"), fail_times=None)
    await compressor.compress(sample_chat)
    assert len(provider.calls) == 5


async def test_backoff_grows_exponentially(keyed_settings, sample_chat, monkeypatch):
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("contextslim.compression.deep.asyncio.sleep", fake_sleep)
    keyed_settings.deep_retry_backoff_seconds = 1.0
    compressor, _ = build(keyed_settings, error=FakeApiError(503, "busy"), fail_times=None)
    await compressor.compress(sample_chat)

    assert delays == [1.0, 2.0]  # attempts 1 and 2 wait; the third gives up


# --- chunking --------------------------------------------------------------


def test_chunking_splits_on_paragraph_boundaries():
    text = "paragraph body here.\n\n" * 40_000
    chunks = DeepCompressor._chunks(text, size=100_000)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(chunk) <= 100_000 for chunk in chunks[:-1])


def test_short_text_is_a_single_chunk():
    assert DeepCompressor._chunks("short") == ["short"]


async def test_long_session_is_chunked_and_merged(keyed_settings, monkeypatch):
    monkeypatch.setattr("contextslim.compression.deep._MAX_CHARS_PER_CALL", 1000)
    part_one = dict(VALID_PAYLOAD, completed=["first half done"], decisions=["A over B"])
    part_two = dict(VALID_PAYLOAD, completed=["second half done"], decisions=["C over D"])
    compressor, provider = build(
        keyed_settings, replies=[json.dumps(part_one), json.dumps(part_two)]
    )

    long_text = "This is a sentence about the project.\n\n" * 100
    result = await compressor.compress(long_text)

    assert len(provider.calls) > 1
    assert result.mode == "deep"
    assert "first half done" in result.capsule.completed
    assert "second half done" in result.capsule.completed
    assert any("chunk" in warning for warning in result.warnings)
