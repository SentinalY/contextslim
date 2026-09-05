"""Raw text minifier behaviour."""

from __future__ import annotations

from contextslim.minify import minify, minify_with_stats


def test_empty_input():
    assert minify("") == ""
    assert minify(None) == ""


def test_trailing_whitespace_removed():
    assert minify("hello   \nworld\t\t") == "hello\nworld"


def test_inner_space_runs_collapsed():
    assert minify("a      b") == "a b"


def test_leading_indentation_preserved():
    """List nesting and quoted structure must survive."""
    out = minify("- item\n    - nested item")
    assert "    - nested item" in out


def test_blank_line_runs_collapsed_to_one():
    assert minify("a\n\n\n\n\nb") == "a\n\nb"


def test_aggressive_mode_removes_all_blank_lines():
    assert minify("a\n\nb", aggressive=True) == "a\nb"


def test_separator_lines_removed():
    out = minify("title\n--------------\nbody")
    assert "-----" not in out
    assert "title" in out and "body" in out


def test_repeated_punctuation_trimmed():
    assert minify("wow!!!!!!!!!!") == "wow!!!"


def test_invisible_characters_stripped():
    assert minify("a​b﻿c") == "abc"


def test_non_breaking_space_normalised():
    assert minify("a b") == "a b"


def test_code_blocks_are_untouched():
    source = 'text\n\n```python\ndef f():\n    x  =  1\n    return  x\n```\n\nmore   text'
    out = minify(source)
    assert "    x  =  1" in out  # indentation and spacing preserved verbatim
    assert "more text" in out  # prose outside the fence still minified


def test_tilde_fences_also_preserved():
    out = minify("~~~\na    b\n~~~")
    assert "a    b" in out


def test_minify_is_idempotent(sample_chat):
    once = minify(sample_chat)
    assert minify(once) == once


def test_stats_report_a_real_saving(sample_chat):
    result = minify_with_stats(sample_chat)
    assert result.minified_chars < result.original_chars
    assert result.minified_tokens <= result.original_tokens
    assert result.reduction_pct >= 0
    assert "text" not in result.as_dict()


def test_content_words_survive_minification(sample_chat):
    out = minify(sample_chat)
    for keyword in ("FastAPI", "JWT", "PostgreSQL", "refresh token"):
        assert keyword in out
