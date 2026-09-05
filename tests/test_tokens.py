"""Token counting, including the offline fallback path."""

from __future__ import annotations

from contextslim import tokens
from contextslim.tokens import TokenCounter, reduction_pct, token_metrics


def test_empty_input_counts_zero():
    assert tokens.count_tokens("") == 0
    assert tokens.count_tokens(None) == 0


def test_counts_grow_with_text_length():
    short = tokens.count_tokens("hello world")
    long = tokens.count_tokens("hello world " * 50)
    assert 0 < short < long


def test_special_tokens_do_not_raise():
    """Chat transcripts contain things like <|endoftext|>; must not explode."""
    assert tokens.count_tokens("<|endoftext|> some text") > 0


def test_fallback_estimator_used_when_encoding_unavailable():
    counter = TokenCounter("definitely-not-a-real-encoding")
    count = counter.count("a" * 400)
    assert counter.is_degraded is True
    assert counter.method == "character-estimate"
    assert count == 100  # 400 chars / 4


def test_fallback_never_returns_zero_for_nonempty_text():
    counter = TokenCounter("definitely-not-a-real-encoding")
    assert counter.count("x") == 1


def test_reduction_pct_math():
    assert reduction_pct(1000, 100) == 90.0
    assert reduction_pct(94_200, 680) == 99.28
    assert reduction_pct(0, 0) == 0.0


def test_reduction_pct_clamps_when_output_is_larger():
    assert reduction_pct(100, 500) == 0.0


def test_token_metrics_payload_shape():
    metrics = token_metrics(1000, 250)
    assert metrics["raw_tokens"] == 1000
    assert metrics["compressed_tokens"] == 250
    assert metrics["tokens_saved"] == 750
    assert metrics["reduction_pct"] == 75.0
    assert "approximate" in metrics["note"].lower()
    assert metrics["counting_method"]


def test_counter_instances_are_cached():
    assert tokens.get_counter("cl100k_base") is tokens.get_counter("cl100k_base")
