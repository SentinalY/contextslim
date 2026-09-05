"""Slim mode - free, offline, deterministic extractive compression.

The pipeline is deliberately simple and explainable:

1. Split the conversation into cleaned sentences (no code, no speaker labels).
2. Route each sentence into one of the six capsule sections using explicit
   labels first, then keyword patterns, then recency.
3. Where a section has more candidates than its budget, rank them with
   sumy's LSA summariser and keep the strongest, in original order.

No API key, no network, no model download, and the same input always produces
the same capsule.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import List, Optional, Sequence

from ..capsule import Capsule
from ..config import Settings, get_settings
from .base import CompressionResult
from .text_utils import (
    RegexTokenizer,
    first_heading,
    meaningful_sentences,
    tail_slice,
    to_words,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing patterns
# ---------------------------------------------------------------------------

# Explicit labels the user or assistant typed. These win over everything.
_LABEL_PATTERNS = {
    "decisions": re.compile(r"^\s*(decision|decided|we decided)\b\s*[:\-]", re.I),
    "constraints": re.compile(r"^\s*(constraint|requirement|rule|limitation)s?\b\s*[:\-]", re.I),
    "next_objective": re.compile(r"^\s*(next objective|next step|next up|todo|to-do)\b\s*[:\-]", re.I),
    "completed": re.compile(r"^\s*(done|completed|finished|shipped)\b\s*[:\-]", re.I),
}

_NEXT_RE = re.compile(
    r"\b(next objective|next step|next up|remaining work|remains|still (?:need|needs|to do)|"
    r"left to do|to-?do|we should (?:then|next)|then implement|upcoming|after that|"
    r"the plan is to|resume (?:from|with))\b",
    re.I,
)

_CONSTRAINT_RE = re.compile(
    r"\b(must not|must be|cannot|can'?t|never|no open|not allowed|forbidden|"
    r"restricted to|required|requires|has to|have to|only (?:if|when|after)|"
    r"frozen|do not|don'?t|limit(?:ed)? to|policy|compliance|deadline|budget)\b",
    re.I,
)

_DECISION_RE = re.compile(
    r"\b(decid\w+|chose|choose|chosen|choosing|agreed|going with|go with|"
    r"we'?ll use|we will use|let'?s use|let'?s go with|opted|settled on|"
    r"instead of|rather than|switch(?:ing|ed)? to|use \w+ (?:rather|instead)|"
    r"i'?d use|recommend(?:ed)?ation)\b",
    re.I,
)

_COMPLETED_RE = re.compile(
    r"\b(added|implemented|wrote|created|built|set up|configured|fixed|"
    r"finished|completed|done|migrated|refactored|deployed|merged|"
    r"now works|working|tested|verified)\b",
    re.I,
)

# Compact stopword list used only if sumy's bundled list cannot be read.
_FALLBACK_STOPWORDS = frozenset(
    """a about after all also an and any are as at be because been but by can could did do does
    for from get had has have he her his how i if in into is it its just like make me more most
    my no not of on one only or other our out over said same see she should so some such than
    that the their them then there these they this those to too up use used using very was we
    were what when where which who will with would you your""".split()
)


class SlimCompressor:
    """Extractive compression into a six-section capsule."""

    mode = "slim"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------
    def _rank(self, sentences: Sequence[str], budget: int) -> List[str]:
        """Keep the ``budget`` most representative sentences, in order."""
        if budget <= 0 or not sentences:
            return []
        if len(sentences) <= budget:
            return list(sentences)

        picked = self._rank_lsa(sentences, budget)
        if not picked:
            picked = self._rank_frequency(sentences, budget)

        chosen = set(picked)
        return [s for s in sentences if s in chosen][:budget]

    def _rank_lsa(self, sentences: Sequence[str], budget: int) -> List[str]:
        try:
            from sumy.models.dom import ObjectDocumentModel, Paragraph, Sentence
            from sumy.summarizers.lsa import LsaSummarizer

            tokenizer = RegexTokenizer()
            document = ObjectDocumentModel(
                [Paragraph([Sentence(text, tokenizer) for text in sentences])]
            )
            summarizer = LsaSummarizer()
            summarizer.stop_words = self._stop_words()
            return [str(sentence) for sentence in summarizer(document, budget)]
        except Exception as exc:  # sumy missing, numpy issue, degenerate matrix
            logger.warning("LSA ranking unavailable (%s); using frequency ranking", exc)
            return []

    @staticmethod
    def _stop_words() -> frozenset:
        try:
            from sumy.utils import get_stop_words

            return frozenset(get_stop_words("english"))
        except Exception:
            return _FALLBACK_STOPWORDS

    def _rank_frequency(self, sentences: Sequence[str], budget: int) -> List[str]:
        """Pure-Python fallback: score by term frequency of content words."""
        stop = self._stop_words()
        frequencies: Counter = Counter()
        for sentence in sentences:
            frequencies.update(w for w in to_words(sentence) if w not in stop and len(w) > 2)
        if not frequencies:
            return list(sentences[:budget])

        peak = max(frequencies.values())
        scored = []
        for index, sentence in enumerate(sentences):
            words = [w for w in to_words(sentence) if w not in stop and len(w) > 2]
            if not words:
                continue
            score = sum(frequencies[w] / peak for w in words) / (len(words) ** 0.5)
            scored.append((score, -index, sentence))
        scored.sort(reverse=True)
        return [sentence for _, _, sentence in scored[:budget]]

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    @staticmethod
    def _route(sentence: str) -> tuple[str, bool]:
        """Return ``(bucket, was_explicitly_labelled)`` for one sentence.

        A sentence the human actually labelled ("Decision: ...") is worth more
        than one matched by keyword, so the flag travels with it and gives it
        priority when the section budget is tight.
        """
        for bucket, pattern in _LABEL_PATTERNS.items():
            if pattern.search(sentence):
                return bucket, True
        if _NEXT_RE.search(sentence):
            return "next_objective", False
        if _CONSTRAINT_RE.search(sentence):
            return "constraints", False
        if _DECISION_RE.search(sentence):
            return "decisions", False
        if _COMPLETED_RE.search(sentence):
            return "completed", False
        return "other", False

    def _select(self, entries: Sequence[tuple[str, bool]], budget: int) -> List[str]:
        """Fill a section: explicit labels first, then ranked keyword matches."""
        if budget <= 0 or not entries:
            return []
        labelled = [text for text, is_labelled in entries if is_labelled]
        inferred = [text for text, is_labelled in entries if not is_labelled]

        chosen = list(dict.fromkeys(labelled))[:budget]
        remaining = budget - len(chosen)
        if remaining > 0:
            chosen.extend(self._rank(inferred, remaining))

        order = {text: index for index, (text, _) in enumerate(entries)}
        return sorted(dict.fromkeys(chosen), key=lambda text: order.get(text, 0))

    @staticmethod
    def _strip_label(sentence: str) -> str:
        for pattern in _LABEL_PATTERNS.values():
            sentence = pattern.sub("", sentence)
        return sentence.strip(" \t-–—:").strip()

    def _budgets(self) -> dict:
        total = max(6, self.settings.slim_sentences)
        return {
            "decisions": max(3, round(total * 0.35)),
            "constraints": max(2, round(total * 0.20)),
            "completed": max(2, round(total * 0.25)),
            "current_state": max(2, round(total * 0.20)),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compress(
        self,
        text: str,
        project: Optional[str] = None,
        title: Optional[str] = None,
    ) -> CompressionResult:
        """Compress ``text`` into a :class:`Capsule`."""
        sentences = meaningful_sentences(text)
        warnings: List[str] = []
        if not sentences:
            warnings.append("No extractable sentences found in the input.")
            return CompressionResult(
                capsule=Capsule(project=project or title or ""),
                mode=self.mode,
                warnings=warnings,
            )

        buckets: dict[str, List[tuple[str, bool]]] = {
            "decisions": [],
            "constraints": [],
            "completed": [],
            "next_objective": [],
            "other": [],
        }
        for sentence in sentences:
            bucket, is_labelled = self._route(sentence)
            buckets[bucket].append((self._strip_label(sentence), is_labelled))

        budgets = self._budgets()

        # CURRENT STATE reflects where the session stopped, so it draws from
        # the tail of the conversation rather than the whole of it.
        leftovers = [text for text, _ in buckets["other"]]
        recent_pool = tail_slice(leftovers or sentences)
        current_state = self._rank(recent_pool, budgets["current_state"])

        # NEXT OBJECTIVE is the most recent forward-looking statement.
        if buckets["next_objective"]:
            next_objective = buckets["next_objective"][-1][0]
        else:
            next_objective = sentences[-1]
            warnings.append(
                "No explicit next objective found; used the final statement of the session."
            )

        capsule = Capsule(
            project=self._derive_project(project, title, text, sentences),
            completed=self._select(buckets["completed"], budgets["completed"]),
            decisions=self._select(buckets["decisions"], budgets["decisions"]),
            current_state=current_state,
            next_objective=next_objective,
            constraints=self._select(buckets["constraints"], budgets["constraints"]),
        )
        return CompressionResult(capsule=capsule, mode=self.mode, warnings=warnings)

    @staticmethod
    def _derive_project(
        project: Optional[str],
        title: Optional[str],
        text: str,
        sentences: Sequence[str],
    ) -> str:
        if project:
            return project
        heading = first_heading(text)
        if heading:
            return heading
        if title:
            return title
        return sentences[0] if sentences else ""
