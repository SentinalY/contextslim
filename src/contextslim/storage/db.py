"""Async SQLite capsule store.

aiosqlite keeps the MCP server and the FastAPI app non-blocking. Every method
opens a short-lived connection: SQLite handles this efficiently, and it avoids
a long-lived connection being bound to the wrong event loop when the same
store is used from two transports.
"""

from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import aiosqlite

from ..capsule import Capsule
from ..config import Settings, get_settings
from ..errors import CapsuleNotFoundError
from ..paths import ensure_parent_dir
from .models import CapsuleRecord, CapsuleVersion, utc_now

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Unambiguous alphabet: no 0/O or 1/I, because session IDs get read aloud
# and retyped into a fresh chat.
_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ID_LENGTH = 8

_INSERT_SQL = """
INSERT INTO capsules (
    session_id, created_at, updated_at, mode, version, title, project,
    capsule_json, capsule_text, raw_tokens, compressed_tokens, reduction_pct,
    source_files, model, fallback_reason, restore_count, last_restored_at
) VALUES (
    :session_id, :created_at, :updated_at, :mode, :version, :title, :project,
    :capsule_json, :capsule_text, :raw_tokens, :compressed_tokens, :reduction_pct,
    :source_files, :model, :fallback_reason, :restore_count, :last_restored_at
)
"""

_UPDATE_SQL = """
UPDATE capsules SET
    updated_at = :updated_at,
    mode = :mode,
    version = :version,
    title = :title,
    project = :project,
    capsule_json = :capsule_json,
    capsule_text = :capsule_text,
    raw_tokens = :raw_tokens,
    compressed_tokens = :compressed_tokens,
    reduction_pct = :reduction_pct,
    source_files = :source_files,
    model = :model,
    fallback_reason = :fallback_reason
WHERE session_id = :session_id
"""


def generate_session_id(length: int = ID_LENGTH) -> str:
    """Return a random, unambiguous, uppercase session ID."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


class CapsuleStore:
    """Persistence for capsules and their version history."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = self.settings.database_path
        self._initialised = False

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def _connect(self):
        ensure_parent_dir(self.db_path)
        connection = await aiosqlite.connect(self.db_path)
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        """Create the schema if needed. Safe to call repeatedly."""
        if self._initialised:
            return
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._connect() as db:
            await db.executescript(schema)
            await db.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )
            await db.commit()
        self._initialised = True
        logger.debug("capsule store ready at %s", self.db_path)

    async def schema_version(self) -> Optional[str]:
        await self.initialize()
        async with self._connect() as db:
            async with db.execute("SELECT value FROM meta WHERE key = 'schema_version'") as cur:
                row = await cur.fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def _unique_session_id(self, db) -> str:
        for _ in range(10):
            candidate = generate_session_id()
            async with db.execute(
                "SELECT 1 FROM capsules WHERE session_id = ?", (candidate,)
            ) as cur:
                if await cur.fetchone() is None:
                    return candidate
        # 32^8 keyspace makes this effectively unreachable, but never loop forever.
        raise RuntimeError("could not allocate a unique session id")

    async def create(self, record: CapsuleRecord) -> CapsuleRecord:
        """Insert a new capsule, allocating a session ID when absent."""
        await self.initialize()
        async with self._connect() as db:
            if not record.session_id:
                record.session_id = await self._unique_session_id(db)
            await db.execute(_INSERT_SQL, record.to_params())
            await db.commit()
        return record

    async def update(
        self,
        session_id: str,
        capsule: Capsule,
        *,
        mode: Optional[str] = None,
        raw_tokens: Optional[int] = None,
        compressed_tokens: Optional[int] = None,
        reduction_pct: Optional[float] = None,
        title: Optional[str] = None,
        project: Optional[str] = None,
        model: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        source_files: Optional[List[str]] = None,
        note: Optional[str] = None,
    ) -> CapsuleRecord:
        """Replace a capsule's content, archiving the previous version first."""
        existing = await self.get(session_id)
        if existing is None:
            raise CapsuleNotFoundError(f"No capsule with session_id '{session_id}'")

        async with self._connect() as db:
            # Archive the state we are about to replace.
            await db.execute(
                """
                INSERT OR IGNORE INTO capsule_versions (
                    session_id, version, created_at, mode, capsule_json,
                    capsule_text, raw_tokens, compressed_tokens, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    existing.session_id,
                    existing.version,
                    existing.updated_at,
                    existing.mode,
                    existing.capsule.model_dump_json(),
                    existing.capsule.render(),
                    existing.raw_tokens,
                    existing.compressed_tokens,
                    note,
                ),
            )

            updated = existing.model_copy(
                update={
                    "capsule": capsule,
                    "version": existing.version + 1,
                    "updated_at": utc_now(),
                    "mode": mode or existing.mode,
                    "raw_tokens": existing.raw_tokens
                    if raw_tokens is None
                    else raw_tokens,
                    "compressed_tokens": existing.compressed_tokens
                    if compressed_tokens is None
                    else compressed_tokens,
                    "reduction_pct": existing.reduction_pct
                    if reduction_pct is None
                    else reduction_pct,
                    "title": title or existing.title,
                    "project": project or existing.project,
                    "model": model or existing.model,
                    "fallback_reason": fallback_reason,
                    "source_files": existing.source_files + list(source_files or []),
                }
            )
            await db.execute(_UPDATE_SQL, updated.to_params())
            await db.commit()
        return updated

    async def mark_restored(self, session_id: str) -> None:
        """Record that a capsule was loaded into a fresh session."""
        async with self._connect() as db:
            await db.execute(
                "UPDATE capsules SET restore_count = restore_count + 1, "
                "last_restored_at = ? WHERE session_id = ?",
                (utc_now(), session_id),
            )
            await db.commit()

    async def delete(self, session_id: str) -> bool:
        """Delete a capsule and its version history. Returns True if it existed."""
        await self.initialize()
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM capsules WHERE session_id = ?", (session_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, session_id: str) -> Optional[CapsuleRecord]:
        await self.initialize()
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM capsules WHERE session_id = ?", (session_id.strip().upper(),)
            ) as cur:
                row = await cur.fetchone()
        return CapsuleRecord.from_row(row) if row else None

    async def list(
        self, limit: int = 20, offset: int = 0, project: Optional[str] = None
    ) -> List[CapsuleRecord]:
        await self.initialize()
        sql = "SELECT * FROM capsules"
        params: list = []
        if project:
            sql += " WHERE project LIKE ?"
            params.append(f"%{project}%")
        sql += " ORDER BY datetime(updated_at) DESC, session_id LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])

        async with self._connect() as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [CapsuleRecord.from_row(row) for row in rows]

    async def search(self, query: str, limit: int = 20) -> List[CapsuleRecord]:
        """Keyword search across capsule text, title and project (SQL LIKE)."""
        await self.initialize()
        needle = f"%{query.strip()}%"
        async with self._connect() as db:
            async with db.execute(
                """
                SELECT * FROM capsules
                WHERE capsule_text LIKE ? COLLATE NOCASE
                   OR IFNULL(title, '')   LIKE ? COLLATE NOCASE
                   OR IFNULL(project, '') LIKE ? COLLATE NOCASE
                   OR session_id          LIKE ? COLLATE NOCASE
                ORDER BY datetime(updated_at) DESC
                LIMIT ?
                """,
                (needle, needle, needle, needle, max(1, limit)),
            ) as cur:
                rows = await cur.fetchall()
        return [CapsuleRecord.from_row(row) for row in rows]

    async def versions(self, session_id: str) -> List[CapsuleVersion]:
        await self.initialize()
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM capsule_versions WHERE session_id = ? ORDER BY version",
                (session_id.strip().upper(),),
            ) as cur:
                rows = await cur.fetchall()
        return [CapsuleVersion.from_row(row) for row in rows]

    async def count(self) -> int:
        await self.initialize()
        async with self._connect() as db:
            async with db.execute("SELECT COUNT(*) AS n FROM capsules") as cur:
                row = await cur.fetchone()
        return int(row["n"])

    async def stats(self) -> dict:
        """Aggregate analytics, computed in SQL so counters cannot drift."""
        await self.initialize()
        async with self._connect() as db:
            async with db.execute(
                """
                SELECT COUNT(*)                        AS total_sessions,
                       IFNULL(SUM(raw_tokens), 0)      AS total_raw_tokens,
                       IFNULL(SUM(compressed_tokens), 0) AS total_compressed_tokens,
                       IFNULL(AVG(reduction_pct), 0)   AS avg_reduction_pct,
                       IFNULL(SUM(restore_count), 0)   AS total_restores,
                       MIN(created_at)                 AS first_session_at,
                       MAX(updated_at)                 AS latest_session_at
                FROM capsules
                """
            ) as cur:
                totals = dict(await cur.fetchone())

            async with db.execute(
                """
                SELECT mode,
                       COUNT(*)                          AS sessions,
                       IFNULL(SUM(raw_tokens), 0)        AS raw_tokens,
                       IFNULL(SUM(compressed_tokens), 0) AS compressed_tokens,
                       IFNULL(AVG(reduction_pct), 0)     AS avg_reduction_pct
                FROM capsules GROUP BY mode
                """
            ) as cur:
                by_mode = {row["mode"]: dict(row) for row in await cur.fetchall()}

        raw = int(totals["total_raw_tokens"])
        compressed = int(totals["total_compressed_tokens"])
        saved = max(0, raw - compressed)
        totals["total_tokens_saved"] = saved
        totals["overall_efficiency_pct"] = round(saved / raw * 100, 2) if raw else 0.0
        totals["avg_reduction_pct"] = round(float(totals["avg_reduction_pct"]), 2)
        for entry in by_mode.values():
            entry["avg_reduction_pct"] = round(float(entry["avg_reduction_pct"]), 2)
            entry["tokens_saved"] = max(0, entry["raw_tokens"] - entry["compressed_tokens"])
        totals["by_mode"] = by_mode
        totals["database_path"] = str(self.db_path)
        return totals

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    async def export_rows(self) -> List[dict]:
        """Every capsule as plain dictionaries (used by tooling and backups)."""
        records = await self.list(limit=10_000)
        return [json.loads(record.model_dump_json()) for record in records]
