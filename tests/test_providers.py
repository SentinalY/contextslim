"""Deep-mode providers: selection, availability, and vendor wire formats.

Both SDK clients are stubbed. Nothing here reaches the network or spends
credit on either provider.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from contextslim.compression.providers import (
    PROVIDER_NAMES,
    AnthropicProvider,
    GeminiProvider,
    get_provider,
)
from contextslim.config import Settings
from contextslim.errors import InvalidInputError


# --- selection -------------------------------------------------------------


def test_gemini_is_the_default(settings):
    assert isinstance(get_provider(settings), GeminiProvider)


def test_anthropic_selected_by_setting(tmp_path):
    settings = Settings(home=tmp_path, deep_provider="anthropic", _env_file=None)
    assert isinstance(get_provider(settings), AnthropicProvider)


def test_explicit_name_overrides_the_setting(settings):
    assert isinstance(get_provider(settings, name="anthropic"), AnthropicProvider)


def test_unknown_provider_raises_with_valid_options(settings):
    with pytest.raises(InvalidInputError) as exc:
        get_provider(settings, name="openai")
    for name in PROVIDER_NAMES:
        assert name in str(exc.value)


def test_both_documented_providers_are_registered():
    assert set(PROVIDER_NAMES) == {"gemini", "anthropic"}


# --- availability ----------------------------------------------------------


def test_gemini_availability_follows_its_own_key(tmp_path):
    without = GeminiProvider(Settings(home=tmp_path, _env_file=None))
    with_key = GeminiProvider(Settings(home=tmp_path, gemini_api_key="gm-x", _env_file=None))
    assert without.available is False
    assert with_key.available is True
    assert "GEMINI_API_KEY" in without.unavailable_reason


def test_anthropic_availability_follows_its_own_key(tmp_path):
    without = AnthropicProvider(Settings(home=tmp_path, _env_file=None))
    with_key = AnthropicProvider(Settings(home=tmp_path, anthropic_api_key="sk-x", _env_file=None))
    assert without.available is False
    assert with_key.available is True
    assert "ANTHROPIC_API_KEY" in without.unavailable_reason


def test_a_providers_key_does_not_enable_the_other(tmp_path):
    settings = Settings(home=tmp_path, gemini_api_key="gm-x", _env_file=None)
    assert GeminiProvider(settings).available is True
    assert AnthropicProvider(settings).available is False


def test_describe_reports_model_and_env_var(tmp_path):
    described = GeminiProvider(Settings(home=tmp_path, _env_file=None)).describe()
    assert described["provider"] == "gemini"
    assert described["key_env_var"] == "GEMINI_API_KEY"
    assert described["model"]
    assert described["available"] is False


def test_models_come_from_settings(tmp_path):
    settings = Settings(
        home=tmp_path,
        gemini_model="gemini-test-model",
        anthropic_model="claude-test-model",
        _env_file=None,
    )
    assert GeminiProvider(settings).model == "gemini-test-model"
    assert AnthropicProvider(settings).model == "claude-test-model"


# --- gemini wire format ----------------------------------------------------


class StubGeminiModels:
    def __init__(self, text="{}"):
        self.text = text
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


class StubGeminiClient:
    def __init__(self, text="{}"):
        self.models = StubGeminiModels(text)
        self.aio = SimpleNamespace(models=self.models)


async def test_gemini_request_shape(tmp_path):
    pytest.importorskip("google.genai")
    settings = Settings(
        home=tmp_path, gemini_api_key="gm-x", gemini_model="gemini-3.6-flash", _env_file=None
    )
    client = StubGeminiClient(text='{"project": "x"}')
    provider = GeminiProvider(settings, client=client)

    output = await provider.generate("SYSTEM RULES", "USER SESSION")

    call = client.models.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert call["contents"] == "USER SESSION"
    assert call["config"].system_instruction == "SYSTEM RULES"
    assert call["config"].max_output_tokens == settings.deep_max_tokens
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].temperature == 0.0
    assert output == '{"project": "x"}'


async def test_gemini_handles_empty_response(tmp_path):
    pytest.importorskip("google.genai")
    settings = Settings(home=tmp_path, gemini_api_key="gm-x", _env_file=None)
    client = StubGeminiClient(text=None)
    assert await GeminiProvider(settings, client=client).generate("s", "u") == ""


# --- anthropic wire format -------------------------------------------------


class StubAnthropicMessages:
    def __init__(self, blocks):
        self.blocks = blocks
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.blocks)


class StubAnthropicClient:
    def __init__(self, blocks=None):
        self.messages = StubAnthropicMessages(
            blocks or [SimpleNamespace(type="text", text='{"project": "x"}')]
        )


async def test_anthropic_request_shape(tmp_path):
    settings = Settings(
        home=tmp_path,
        deep_provider="anthropic",
        anthropic_api_key="sk-x",
        anthropic_model="claude-haiku-4-5",
        _env_file=None,
    )
    client = StubAnthropicClient()
    provider = AnthropicProvider(settings, client=client)

    output = await provider.generate("SYSTEM RULES", "USER SESSION")

    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["system"] == "SYSTEM RULES"
    assert call["max_tokens"] == settings.deep_max_tokens
    assert call["messages"] == [{"role": "user", "content": "USER SESSION"}]
    assert output == '{"project": "x"}'


async def test_anthropic_joins_text_blocks_and_ignores_others(tmp_path):
    settings = Settings(home=tmp_path, anthropic_api_key="sk-x", _env_file=None)
    client = StubAnthropicClient(
        blocks=[
            SimpleNamespace(type="text", text='{"pro'),
            SimpleNamespace(type="thinking", text="ignore me"),
            SimpleNamespace(type="text", text='ject": "x"}'),
        ]
    )
    output = await AnthropicProvider(settings, client=client).generate("s", "u")
    assert output == '{"project": "x"}'
