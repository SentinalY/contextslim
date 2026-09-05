"""Row models for the capsule store."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from ..capsule import Capsule


def utc_now() -> str:
    """Current UTC time as a sortable ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CapsuleRecord(BaseModel):
    """One stored session, as it lives in the ``capsules`` table."""

    session_id: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    mode: str = "slim"
    version: int = 1
    title: Optional[str] = None
    project: Optional[str] = None
    capsule: Capsule = Field(default_factory=Capsule)
    raw_tokens: int = 0
    compressed_tokens: int = 0
    reduction_pct: float = 0.0
    source_files: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    fallback_reason: Optional[str] = None
    restore_count: int = 0
    last_restored_at: Optional[str] = None

    # -- conversions ----------------------------------------------------
    @classmethod
    def from_row(cls, row) -> "CapsuleRecord":
        """Build a record from an ``aiosqlite.Row``."""
        data = dict(row)
        capsule_json = data.pop("capsule_json", "{}")
        data.pop("capsule_text", None)
        data["capsule"] = Capsule(**json.loads(capsule_json))
        data["source_files"] = json.loads(data.get("source_files") or "[]")
        return cls(**data)

    def to_params(self) -> dict:
        """Flatten to the parameter dict used by INSERT/UPDATE statements."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "version": self.version,
            "title": self.title,
            "project": self.project,
            "capsule_json": self.capsule.model_dump_json(),
            "capsule_text": self.capsule.render(),
            "raw_tokens": self.raw_tokens,
            "compressed_tokens": self.compressed_tokens,
            "reduction_pct": self.reduction_pct,
            "source_files": json.dumps(self.source_files),
            "model": self.model,
            "fallback_reason": self.fallback_reason,
            "restore_count": self.restore_count,
            "last_restored_at": self.last_restored_at,
        }

    # -- presentation ---------------------------------------------------
    @property
    def tokens_saved(self) -> int:
        return max(0, self.raw_tokens - self.compressed_tokens)

    def summary(self) -> dict:
        """The compact shape returned by list_capsules / search_capsules."""
        return {
            "session_id": self.session_id,
            "title": self.title or self.project or "(untitled session)",
            "project": self.project,
            "mode": self.mode,
            "version": self.version,
            "raw_tokens": self.raw_tokens,
            "compressed_tokens": self.compressed_tokens,
            "reduction_pct": self.reduction_pct,
            "tokens_saved": self.tokens_saved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "restore_count": self.restore_count,
            "next_objective": self.capsule.next_objective,
        }


class CapsuleVersion(BaseModel):
    """An archived earlier state of a capsule."""

    session_id: str
    version: int
    created_at: str
    mode: str
    capsule: Capsule
    raw_tokens: int = 0
    compressed_tokens: int = 0
    note: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "CapsuleVersion":
        data = dict(row)
        data.pop("id", None)
        data.pop("capsule_text", None)
        data["capsule"] = Capsule(**json.loads(data.pop("capsule_json")))
        return cls(**data)
