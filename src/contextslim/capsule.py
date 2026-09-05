"""The Context Capsule - a machine-readable save file, not a summary.

Six sections, each with a defined purpose:

    PROJECT         what is being built, in one or two lines
    COMPLETED       work already finished, so it is never redone
    DECISIONS       choices made and the alternative rejected
    CURRENT STATE   where the session stopped
    NEXT OBJECTIVE  the single next thing to do
    CONSTRAINTS     rules the assistant must not violate

Both compressors emit this structure, storage persists it as JSON, and
``load_capsule`` renders it back into a restore prompt.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field, field_validator

SECTION_ORDER: tuple[str, ...] = (
    "PROJECT",
    "COMPLETED",
    "DECISIONS",
    "CURRENT STATE",
    "NEXT OBJECTIVE",
    "CONSTRAINTS",
)

# Sections rendered as bullet lists; the other two are free prose.
_LIST_SECTIONS = {"COMPLETED", "DECISIONS", "CURRENT STATE", "CONSTRAINTS"}

_FIELD_BY_SECTION = {
    "PROJECT": "project",
    "COMPLETED": "completed",
    "DECISIONS": "decisions",
    "CURRENT STATE": "current_state",
    "NEXT OBJECTIVE": "next_objective",
    "CONSTRAINTS": "constraints",
}

_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(" + "|".join(SECTION_ORDER) + r")(?:\*\*)?\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


def _clean_items(values: Iterable[str]) -> List[str]:
    """Trim, drop empties, and de-duplicate while preserving order."""
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        item = re.sub(r"\s+", " ", _BULLET_RE.sub("", str(value))).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


class Capsule(BaseModel):
    """A structured session state capsule."""

    project: str = Field(default="", description="What is being built.")
    completed: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    current_state: List[str] = Field(default_factory=list)
    next_objective: str = Field(default="")
    constraints: List[str] = Field(default_factory=list)

    @field_validator("completed", "decisions", "current_state", "constraints", mode="before")
    @classmethod
    def _coerce_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [line for line in value.splitlines()]
        return _clean_items(value)

    @field_validator("project", "next_objective", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            value = " ".join(str(v) for v in value)
        return re.sub(r"\s+", " ", str(value)).strip()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self) -> str:
        """Render the capsule as the canonical six-section text block."""
        blocks: List[str] = []
        for section in SECTION_ORDER:
            field = _FIELD_BY_SECTION[section]
            value = getattr(self, field)
            if section in _LIST_SECTIONS:
                body = "\n".join(f"- {item}" for item in value) if value else "- (none recorded)"
            else:
                body = value or "(none recorded)"
            blocks.append(f"## {section}\n{body}")
        return "\n\n".join(blocks)

    def to_restore_prompt(
        self,
        session_id: str,
        created_at: Optional[str] = None,
        mode: Optional[str] = None,
        version: Optional[int] = None,
    ) -> str:
        """Render the block that boots a fresh chat with this working memory."""
        meta_bits = [f"id {session_id}"]
        if mode:
            meta_bits.append(f"{mode} mode")
        if version and version > 1:
            meta_bits.append(f"v{version}")
        if created_at:
            meta_bits.append(f"saved {created_at}")
        meta = " · ".join(meta_bits)

        return (
            f"[CONTEXT CAPSULE RESTORED — {meta}]\n\n"
            "You are resuming a previous working session. Everything below is "
            "established context from that session: treat it as already agreed, "
            "do not re-derive it, and do not contradict it. Honour every item "
            "under CONSTRAINTS. When you reply, continue from NEXT OBJECTIVE.\n\n"
            f"{self.render()}\n\n"
            "[END CAPSULE] Acknowledge in one line, then continue the work."
        )

    # ------------------------------------------------------------------
    # Parsing and merging
    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "Capsule":
        """Parse capsule text back into a model. Unknown text is ignored."""
        if not text:
            return cls()

        matches = list(_HEADING_RE.finditer(text))
        if not matches:
            return cls()

        data: dict = {}
        for index, match in enumerate(matches):
            section = match.group(1).upper()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if body.lower().startswith("(none recorded)"):
                body = ""
            field = _FIELD_BY_SECTION[section]
            if section in _LIST_SECTIONS:
                data[field] = [
                    line
                    for line in body.splitlines()
                    if line.strip() and "(none recorded)" not in line.lower()
                ]
            else:
                data[field] = body
        return cls(**data)

    def merge(self, other: "Capsule") -> "Capsule":
        """Return a capsule combining ``self`` with newer progress in ``other``.

        List sections accumulate (de-duplicated, original order kept), while
        ``project`` and ``next_objective`` are replaced by the newer values
        when present. This is what makes a capsule a living project memory
        rather than a one-shot snapshot.
        """
        return Capsule(
            project=other.project or self.project,
            completed=self.completed + other.completed,
            decisions=self.decisions + other.decisions,
            current_state=other.current_state or self.current_state,
            next_objective=other.next_objective or self.next_objective,
            constraints=self.constraints + other.constraints,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.project,
                self.completed,
                self.decisions,
                self.current_state,
                self.next_objective,
                self.constraints,
            ]
        )

    @property
    def item_count(self) -> int:
        return (
            len(self.completed)
            + len(self.decisions)
            + len(self.current_state)
            + len(self.constraints)
            + (1 if self.project else 0)
            + (1 if self.next_objective else 0)
        )
