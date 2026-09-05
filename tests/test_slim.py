"""Slim mode compression - offline, deterministic, structured."""

from __future__ import annotations

import pytest

from contextslim.capsule import Capsule
from contextslim.compression.slim import SlimCompressor
from contextslim.compression.text_utils import (
    meaningful_sentences,
    reflow,
    split_sentences,
    strip_code_blocks,
    strip_speaker_prefix,
)
from contextslim.config import Settings
from contextslim.tokens import count_tokens


@pytest.fixture
def compressor(settings) -> SlimCompressor:
    return SlimCompressor(settings)


# --- text utilities --------------------------------------------------------


def test_code_blocks_are_replaced_by_a_marker():
    out = strip_code_blocks("before\n```python\nx = 1\n```\nafter")
    assert "x = 1" not in out
    assert "[code block]" in out


def test_speaker_prefixes_removed():
    assert strip_speaker_prefix("**User (Turn 5):** hello") == "hello"
    assert strip_speaker_prefix("Assistant: hi") == "hi"
    assert strip_speaker_prefix("plain line") == "plain line"


def test_sentence_split_keeps_abbreviations_intact():
    sentences = split_sentences("Use RS256, e.g. with a JWKS endpoint. Then rotate keys.")
    assert any("e.g. with a JWKS" in s for s in sentences)
    assert len(sentences) == 2


def test_reflow_rejoins_hard_wrapped_prose():
    wrapped = "Decision: RS256 with a JWKS endpoint at\n/.well-known/jwks.json, rotated quarterly."
    assert reflow(wrapped).count("\n") == 0


def test_reflow_does_not_merge_separate_bullets():
    assert reflow("- first item\n- second item").count("\n") == 1


def test_reflow_does_not_merge_separate_speakers():
    text = "**User (Turn 1):** something here\n**Assistant (Turn 2):** a reply here"
    assert reflow(text).count("\n") == 1


def test_wrapped_sentences_are_not_truncated(sample_chat):
    """Regression: capsule bullets must be whole thoughts, not line fragments."""
    sentences = meaningful_sentences(sample_chat)
    fragments = [s for s in sentences if s.rstrip().endswith((" at", " and", " the", " so", " plus"))]
    assert fragments == []


def test_meaningful_sentences_drop_short_and_duplicate_lines(sample_chat):
    sentences = meaningful_sentences(sample_chat)
    assert all(len(s) >= 24 for s in sentences)
    assert len(sentences) == len(set(s.lower() for s in sentences))


# --- compression -----------------------------------------------------------


def test_capsule_has_every_section_populated(compressor, sample_chat):
    capsule = compressor.compress(sample_chat).capsule
    assert capsule.project
    assert capsule.decisions
    assert capsule.constraints
    assert capsule.completed
    assert capsule.current_state
    assert capsule.next_objective


def test_decisions_capture_real_choices(compressor, sample_chat):
    decisions = " ".join(compressor.compress(sample_chat).capsule.decisions).lower()
    assert "postgresql" in decisions or "argon2" in decisions or "rs256" in decisions


def test_constraints_capture_hard_rules(compressor, sample_chat):
    constraints = " ".join(compressor.compress(sample_chat).capsule.constraints).lower()
    assert "redis" in constraints or "corp.com" in constraints or "signup" in constraints


def test_next_objective_is_forward_looking(compressor, sample_chat):
    capsule = compressor.compress(sample_chat).capsule
    assert capsule.next_objective
    assert len(capsule.next_objective) > 20


def test_compression_actually_reduces_tokens(compressor, sample_chat):
    capsule = compressor.compress(sample_chat).capsule
    raw = count_tokens(sample_chat)
    compressed = count_tokens(capsule.render())
    assert compressed < raw
    assert (raw - compressed) / raw > 0.5  # at least half the tokens removed


def test_compression_is_deterministic(compressor, sample_chat):
    first = compressor.compress(sample_chat).capsule
    second = compressor.compress(sample_chat).capsule
    assert first.model_dump() == second.model_dump()


def test_no_code_leaks_into_the_capsule(compressor, sample_chat):
    rendered = compressor.compress(sample_chat).capsule.render()
    assert "__tablename__" not in rendered
    assert "async def" not in rendered


def test_no_speaker_labels_leak_into_the_capsule(compressor, sample_chat):
    rendered = compressor.compress(sample_chat).capsule.render()
    assert "**User" not in rendered
    assert "Assistant:" not in rendered


def test_budget_is_respected(sample_chat, tmp_path):
    tight = SlimCompressor(Settings(home=tmp_path, slim_sentences=6, _env_file=None))
    loose = SlimCompressor(Settings(home=tmp_path, slim_sentences=30, _env_file=None))
    tight_capsule = tight.compress(sample_chat).capsule
    loose_capsule = loose.compress(sample_chat).capsule
    assert tight_capsule.item_count <= loose_capsule.item_count
    assert len(tight_capsule.decisions) <= 3


def test_explicit_project_overrides_derived_one(compressor, sample_chat):
    capsule = compressor.compress(sample_chat, project="Portal auth rewrite").capsule
    assert capsule.project == "Portal auth rewrite"


def test_project_derived_from_heading(compressor, sample_chat):
    capsule = compressor.compress(sample_chat).capsule
    assert "authentication" in capsule.project.lower()


def test_empty_input_returns_empty_capsule_with_warning(compressor):
    result = compressor.compress("")
    assert isinstance(result.capsule, Capsule)
    assert result.capsule.is_empty
    assert result.warnings


def test_short_input_still_produces_a_capsule(compressor):
    result = compressor.compress(
        "We decided to use SQLite for local storage because it needs no server."
    )
    assert result.capsule.decisions or result.capsule.current_state
    assert result.mode == "slim"


def test_result_metadata(compressor, sample_chat):
    result = compressor.compress(sample_chat)
    assert result.mode == "slim"
    assert result.used_fallback is False


def test_frequency_ranking_fallback_matches_budget(compressor, sample_chat):
    sentences = meaningful_sentences(sample_chat)
    picked = compressor._rank_frequency(sentences, 5)
    assert len(picked) == 5
    assert all(p in sentences for p in picked)


def test_rank_preserves_original_order(compressor, sample_chat):
    sentences = meaningful_sentences(sample_chat)
    picked = compressor._rank(sentences, 6)
    positions = [sentences.index(p) for p in picked]
    assert positions == sorted(positions)
