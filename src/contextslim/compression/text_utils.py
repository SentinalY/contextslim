"""Offline text splitting utilities.

sumy's default tokenizer depends on NLTK's ``punkt`` model, which is a runtime
download. That would make a fresh clone fail on a machine with no network -
exactly the portability problem this project is supposed to avoid. So
ContextSlim ships its own regex tokenizer that satisfies sumy's interface
(``to_sentences`` / ``to_words``) and needs no downloaded data at all.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

# Fenced code blocks are removed before sentence extraction: code belongs in
# the conversation, not in a capsule bullet.
_CODE_FENCE_RE = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]{1,80})`")

# "**User (Turn 5):**", "Assistant:", "> Human:" and similar speaker labels.
_SPEAKER_RE = re.compile(
    r"^\s*[>*_#\s]*(?:\*\*)?\s*"
    r"(user|assistant|human|ai|system|me|you|claude|gpt|chatgpt|q|a)"
    r"\s*(?:\([^)]{0,40}\))?\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*",
    re.IGNORECASE,
)

_MARKDOWN_NOISE_RE = re.compile(r"^[#>\s]*|[*_`]{1,3}")
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")

# Sentence boundary: a terminator followed by whitespace. The fixed-width
# lookbehinds keep common abbreviations from splitting mid-sentence.
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bvs\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)"
    r"(?<!\bSt\.)(?<!\betc\.)(?<!\bFig\.)(?<!\bNo\.)(?<!\bapprox\.)"
    r"(?<=[.!?])[\"')\]]*\s+"
)

_WORD_RE = re.compile(r"[A-Za-z0-9_'+#.-]+")

MIN_SENTENCE_CHARS = 24
MAX_SENTENCE_CHARS = 400


def strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks, keeping a marker so context is not lost."""
    return _CODE_FENCE_RE.sub(" [code block] ", text or "")


def strip_speaker_prefix(line: str) -> str:
    """Remove a leading speaker label such as ``**User (Turn 5):**``."""
    return _SPEAKER_RE.sub("", line or "", count=1)


def clean_sentence(sentence: str) -> str:
    """Normalise one sentence for storage in a capsule bullet."""
    text = _BULLET_RE.sub("", sentence or "")
    text = strip_speaker_prefix(text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _MARKDOWN_NOISE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t-–—:")
    return text.strip()


def reflow(text: str) -> str:
    """Re-join hard-wrapped prose so sentences are not split mid-thought.

    Chat exports and pasted transcripts are frequently wrapped at 80 columns.
    Splitting those line by line would produce fragments like "RS256 with a
    JWKS endpoint at" - useless in a capsule. A continuation line (one that
    does not start a bullet, heading, quote, table row or speaker turn, and
    whose predecessor did not end a sentence) is folded into the line above.
    """
    lines: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            lines.append("")
            continue

        stripped = line.lstrip()
        starts_block = bool(
            _BULLET_RE.match(line)
            or stripped.startswith(("#", ">", "|", "```", "~~~"))
            or _SPEAKER_RE.match(line)
        )
        previous_continues = bool(
            lines and lines[-1].strip() and not lines[-1].rstrip().endswith((".", "!", "?", ":"))
        )
        if previous_continues and not starts_block:
            lines[-1] = lines[-1].rstrip() + " " + stripped
        else:
            lines.append(line)
    return "\n".join(lines)


def split_sentences(text: str) -> List[str]:
    """Split ``text`` into cleaned sentences.

    Wrapped lines are re-joined first, then each logical line is split on
    sentence boundaries. Working line by line (rather than over the whole
    document) keeps bullets and chat turns from merging into each other.
    """
    if not text:
        return []

    sentences: List[str] = []
    for raw_line in reflow(strip_code_blocks(text)).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for part in _SENTENCE_SPLIT_RE.split(line):
            cleaned = clean_sentence(part)
            if not cleaned:
                continue
            if len(cleaned) > MAX_SENTENCE_CHARS:
                cleaned = cleaned[: MAX_SENTENCE_CHARS - 1].rsplit(" ", 1)[0] + "…"
            sentences.append(cleaned)
    return sentences


def meaningful_sentences(text: str, min_chars: int = MIN_SENTENCE_CHARS) -> List[str]:
    """Sentences long enough to carry information, de-duplicated in order."""
    seen: set[str] = set()
    out: List[str] = []
    for sentence in split_sentences(text):
        if len(sentence) < min_chars:
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sentence)
    return out


def to_words(sentence: str) -> Tuple[str, ...]:
    """Lowercased word tokens for a sentence."""
    return tuple(_WORD_RE.findall((sentence or "").lower()))


class RegexTokenizer:
    """A sumy-compatible tokenizer that needs no downloaded corpora."""

    def __init__(self, language: str = "english") -> None:
        self.language = language

    def to_sentences(self, paragraph: str) -> Tuple[str, ...]:
        return tuple(split_sentences(paragraph))

    def to_words(self, sentence: str) -> Tuple[str, ...]:
        return to_words(sentence)


def first_heading(text: str) -> str:
    """Return the first Markdown heading in ``text``, if any."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            heading = re.sub(r"^session\s*[:\-]\s*", "", heading, flags=re.IGNORECASE)
            if heading:
                return heading
    return ""


def tail_slice(items: Sequence[str], fraction: float = 0.35, minimum: int = 4) -> List[str]:
    """The most recent portion of a sequence, used for CURRENT STATE."""
    if not items:
        return []
    size = max(minimum, int(len(items) * fraction))
    return list(items[-size:])
