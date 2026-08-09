"""
ContextSlim AI - Storage Layer
Uses aiosqlite to persist Context Capsules to a local .db file.
"""

import aiosqlite
import json
from datetime import datetime, timezone
from typing import Optional

import os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contextslim.db")


async def init_db():
    """Create the capsules table if it doesn't exist yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS capsules (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                original_turn_count INTEGER,
                token_count_before INTEGER,
                token_count_after INTEGER,
                compressed_content TEXT NOT NULL
            )
        """)
        await db.commit()


async def save_capsule(
    capsule_id: str,
    session_id: str,
    mode: str,
    original_turn_count: int,
    token_count_before: int,
    token_count_after: int,
    compressed_content: dict,
) -> None:
    """Save a new Context Capsule to the database. Content is serialized to JSON."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO capsules
            (id, session_id, created_at, mode, original_turn_count,
             token_count_before, token_count_after, compressed_content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capsule_id,
                session_id,
                datetime.now(timezone.utc).isoformat(),
                mode,
                original_turn_count,
                token_count_before,
                token_count_after,
                json.dumps(compressed_content),
            ),
        )
        await db.commit()


async def get_capsule(capsule_id: str) -> Optional[dict]:
    """Load a single capsule by its ID. Returns None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM capsules WHERE id = ?", (capsule_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["compressed_content"] = json.loads(result["compressed_content"])
        return result


async def list_capsules(session_id: Optional[str] = None) -> list[dict]:
    """List lightweight summaries of saved capsules, optionally filtered by session."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if session_id:
            cursor = await db.execute(
                """SELECT id, session_id, created_at, mode,
                   original_turn_count, token_count_before, token_count_after
                   FROM capsules WHERE session_id = ? ORDER BY created_at DESC""",
                (session_id,),
            )
        else:
            cursor = await db.execute(
                """SELECT id, session_id, created_at, mode,
                   original_turn_count, token_count_before, token_count_after
                   FROM capsules ORDER BY created_at DESC"""
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_stats() -> dict:
    """Return aggregate compression optimization metrics across all stored records."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*), SUM(token_count_before), SUM(token_count_after) FROM capsules"
        )
        count, total_before, total_after = await cursor.fetchone()
        total_before = total_before or 0
        total_after = total_after or 0
        tokens_saved = total_before - total_after
        compression_ratio = (
            round(total_after / total_before, 3) if total_before else None
        )
        return {
            "total_capsules": count,
            "total_tokens_before": total_before,
            "total_tokens_after": total_after,
            "tokens_saved": tokens_saved,
            "avg_compression_ratio": compression_ratio,
        }


async def search_capsules(query: str, session_id: Optional[str] = None) -> list[dict]:
    """Search capsules by keyword match against their compressed content."""
    like_query = f"%{query}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if session_id:
            cursor = await db.execute(
                """SELECT id, session_id, created_at, mode,
                   original_turn_count, token_count_before, token_count_after, compressed_content
                   FROM capsules
                   WHERE session_id = ? AND compressed_content LIKE ?
                   ORDER BY created_at DESC""",
                (session_id, like_query),
            )
        else:
            cursor = await db.execute(
                """SELECT id, session_id, created_at, mode,
                   original_turn_count, token_count_before, token_count_after, compressed_content
                   FROM capsules
                   WHERE compressed_content LIKE ?
                   ORDER BY created_at DESC""",
                (like_query,),
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["compressed_content"] = json.loads(d["compressed_content"])
            results.append(d)
        return results


async def update_capsule(
    capsule_id: str,
    compressed_content: dict,
    token_count_after: int,
) -> bool:
    """Overwrite a capsule's compressed_content and token_count_after. Returns True if a row was updated."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE capsules SET compressed_content = ?, token_count_after = ? WHERE id = ?",
            (json.dumps(compressed_content), token_count_after, capsule_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    
    