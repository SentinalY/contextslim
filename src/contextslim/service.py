"""Orchestration layer - the whole product, with no transport attached.

Every MCP tool and every REST route is a thin wrapper over one method here.
Keeping the logic transport-agnostic means the behaviour is testable without
an MCP client or an HTTP server in the loop, and adding a third transport
later costs nothing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Sequence

from .capsule import Capsule
from .compression.base import MODE_DESCRIPTIONS, MODES
from .compression.deep import DeepCompressor
from .compression.slim import SlimCompressor
from .config import Settings, get_settings
from .errors import CapsuleNotFoundError, InvalidInputError
from .ingest import FileIngestor
from .minify import minify
from .paths import ensure_dir, ensure_parent_dir, expand
from .storage import CapsuleRecord, CapsuleStore
from .tokens import count_tokens, reduction_pct

logger = logging.getLogger(__name__)

HEALTH_HEALTHY = "HEALTHY"
HEALTH_WARNING = "WARNING"
HEALTH_CRITICAL = "CRITICAL"

EXPORT_FORMATS = ("txt", "json")


class ContextSlimService:
    """All eight capabilities, in one place."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        store: Optional[CapsuleStore] = None,
        deep_compressor: Optional[DeepCompressor] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_runtime_dirs()
        self.store = store or CapsuleStore(self.settings)
        self.slim = SlimCompressor(self.settings)
        self.deep = deep_compressor or DeepCompressor(self.settings)
        self.ingestor = FileIngestor(self.settings)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _count(self, text: str) -> int:
        return count_tokens(text, self.settings.token_encoding)

    @staticmethod
    def _validate_mode(mode: str) -> str:
        normalised = (mode or "slim").strip().lower()
        if normalised not in MODES:
            raise InvalidInputError(
                f"Unknown mode '{mode}'. Valid modes: {', '.join(MODES)}."
            )
        return normalised

    async def _compress(self, text: str, mode: str, project, title):
        if mode == "deep":
            return await self.deep.compress(text, project=project, title=title)
        return self.slim.compress(text, project=project, title=title)

    def _gather_input(
        self, chat_history: Optional[str], file_paths: Optional[Sequence[str]]
    ) -> tuple[str, dict]:
        """Combine raw chat text with any ingested documents."""
        pieces: List[str] = []
        if chat_history and chat_history.strip():
            pieces.append(chat_history.strip())

        ingestion: dict = {"file_count": 0, "files": [], "errors": [], "total_tokens": 0}
        if file_paths:
            report = self.ingestor.ingest_many(list(file_paths))
            ingestion = report.as_dict()
            if report.markdown:
                pieces.append(report.markdown)

        combined = "\n\n".join(pieces)
        if not combined.strip():
            detail = f" Ingestion errors: {'; '.join(ingestion['errors'])}" if ingestion["errors"] else ""
            raise InvalidInputError(
                "Nothing to compress: provide chat_history text or readable file_paths." + detail
            )
        return combined, ingestion

    # ------------------------------------------------------------------
    # 1. extract_session_state
    # ------------------------------------------------------------------
    async def extract_session_state(
        self,
        chat_history: Optional[str] = None,
        mode: str = "slim",
        project: Optional[str] = None,
        title: Optional[str] = None,
        file_paths: Optional[Sequence[str]] = None,
    ) -> dict:
        """Compress a session into a stored Context Capsule."""
        mode = self._validate_mode(mode)
        combined, ingestion = self._gather_input(chat_history, file_paths)

        raw_tokens = self._count(combined)
        minified = minify(combined)
        minified_tokens = self._count(minified)

        result = await self._compress(minified, mode, project, title)
        capsule_text = result.capsule.render()
        compressed_tokens = self._count(capsule_text)

        record = await self.store.create(
            CapsuleRecord(
                session_id="",
                mode=result.mode,
                title=title,
                project=project or result.capsule.project or None,
                capsule=result.capsule,
                raw_tokens=raw_tokens,
                compressed_tokens=compressed_tokens,
                reduction_pct=reduction_pct(raw_tokens, compressed_tokens),
                source_files=[f["name"] for f in ingestion["files"]],
                model=result.model,
                fallback_reason=result.fallback_reason,
            )
        )

        payload = {
            "ok": True,
            "session_id": record.session_id,
            "mode": record.mode,
            "requested_mode": mode,
            "model": record.model,
            "provider": result.provider,
            "project": record.project,
            "metrics": {
                "raw_tokens": raw_tokens,
                "minified_tokens": minified_tokens,
                "compressed_tokens": compressed_tokens,
                "tokens_saved": record.tokens_saved,
                "reduction_pct": record.reduction_pct,
                "minifier_saved_tokens": max(0, raw_tokens - minified_tokens),
                "counting_note": "Token counts are approximate.",
            },
            "capsule": record.capsule.model_dump(),
            "capsule_preview": capsule_text,
            "ingestion": ingestion,
            "warnings": list(result.warnings),
            "restore_hint": (
                f"Open a new chat and say: load capsule {record.session_id}"
            ),
            "summary": (
                f"Saved session {record.session_id} in {record.mode} mode: "
                f"{raw_tokens:,} -> {compressed_tokens:,} approx. tokens "
                f"({record.reduction_pct}% reduction). "
                f"Restore with: load capsule {record.session_id}"
            ),
        }
        if result.fallback_reason:
            payload["fallback_reason"] = result.fallback_reason
            payload["summary"] += f" (deep mode fell back to slim: {result.fallback_reason})"
        return payload

    # ------------------------------------------------------------------
    # 2. load_capsule
    # ------------------------------------------------------------------
    async def load_capsule(self, session_id: str) -> dict:
        """Restore a stored session as a ready-to-paste restore prompt."""
        if not (session_id or "").strip():
            raise InvalidInputError("session_id is required.")

        record = await self.store.get(session_id)
        if record is None:
            recent = await self.store.list(limit=5)
            known = ", ".join(r.session_id for r in recent) or "none stored yet"
            raise CapsuleNotFoundError(
                f"No capsule with id '{session_id}'. Recent sessions: {known}."
            )

        await self.store.mark_restored(record.session_id)
        restore_prompt = record.capsule.to_restore_prompt(
            record.session_id,
            created_at=record.created_at,
            mode=record.mode,
            version=record.version,
        )
        return {
            "ok": True,
            "session_id": record.session_id,
            "mode": record.mode,
            "version": record.version,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "project": record.project,
            "capsule": record.capsule.model_dump(),
            "restore_prompt": restore_prompt,
            "metrics": {
                "raw_tokens": record.raw_tokens,
                "compressed_tokens": record.compressed_tokens,
                "tokens_saved": record.tokens_saved,
                "reduction_pct": record.reduction_pct,
            },
            "summary": (
                f"Session {record.session_id} restored (v{record.version}, "
                f"{record.mode} mode). {record.tokens_saved:,} approx. tokens saved "
                f"versus replaying the original session. "
                f"Next objective: {record.capsule.next_objective or 'not recorded'}"
            ),
        }

    # ------------------------------------------------------------------
    # 3. list_capsules
    # ------------------------------------------------------------------
    async def list_capsules(self, limit: int = 20, project: Optional[str] = None) -> dict:
        records = await self.store.list(limit=limit, project=project)
        return {
            "ok": True,
            "count": len(records),
            "capsules": [record.summary() for record in records],
            "summary": (
                f"{len(records)} capsule(s) stored"
                + (f" for project matching '{project}'" if project else "")
                + ("." if records else ". Run extract_session_state to create one.")
            ),
        }

    # ------------------------------------------------------------------
    # 4. get_stats
    # ------------------------------------------------------------------
    async def get_stats(self) -> dict:
        stats = await self.store.stats()
        return {
            "ok": True,
            **stats,
            "modes": MODE_DESCRIPTIONS,
            "summary": (
                f"{stats['total_sessions']} session(s) compressed. "
                f"{stats['total_raw_tokens']:,} approx. tokens processed, "
                f"{stats['total_tokens_saved']:,} saved "
                f"({stats['overall_efficiency_pct']}% overall efficiency)."
            ),
        }

    # ------------------------------------------------------------------
    # 5. check_context_health
    # ------------------------------------------------------------------
    def check_context_health(
        self,
        token_count: Optional[int] = None,
        chat_history: Optional[str] = None,
    ) -> dict:
        """Classify a conversation's size so the AI can self-trigger compression."""
        if token_count is None and not chat_history:
            raise InvalidInputError("Provide either token_count or chat_history.")

        if token_count is None:
            token_count = self._count(chat_history or "")
        token_count = max(0, int(token_count))

        warning = self.settings.health_warning_tokens
        critical = self.settings.health_critical_tokens
        window = self.settings.context_window_tokens

        if token_count >= critical:
            status = HEALTH_CRITICAL
            recommendation = (
                "Compress now. Call extract_session_state(mode='deep') and continue "
                "in a fresh chat with the returned capsule."
            )
        elif token_count >= warning:
            status = HEALTH_WARNING
            recommendation = (
                "Consider compressing soon. Quality degrades and cost compounds "
                "as history grows."
            )
        else:
            status = HEALTH_HEALTHY
            recommendation = "No action needed."

        return {
            "ok": True,
            "status": status,
            "token_count": token_count,
            "window_used_pct": round(token_count / window * 100, 2) if window else 0.0,
            "thresholds": {
                "healthy_below": warning,
                "warning_at": warning,
                "critical_at": critical,
                "context_window": window,
            },
            "should_compress": status != HEALTH_HEALTHY,
            "recommendation": recommendation,
            "summary": (
                f"{status}: conversation at approximately {token_count:,} tokens "
                f"({round(token_count / window * 100, 1) if window else 0}% of a "
                f"{window:,}-token window). {recommendation}"
            ),
        }

    # ------------------------------------------------------------------
    # 6. update_capsule
    # ------------------------------------------------------------------
    async def update_capsule(
        self,
        session_id: str,
        chat_history: Optional[str] = None,
        mode: str = "slim",
        note: Optional[str] = None,
        file_paths: Optional[Sequence[str]] = None,
    ) -> dict:
        """Fold a new work block into an existing capsule, keeping history."""
        mode = self._validate_mode(mode)
        existing = await self.store.get(session_id)
        if existing is None:
            raise CapsuleNotFoundError(f"No capsule with id '{session_id}'.")

        combined, ingestion = self._gather_input(chat_history, file_paths)
        new_raw_tokens = self._count(combined)
        result = await self._compress(
            minify(combined), mode, existing.project, existing.title
        )

        merged = existing.capsule.merge(result.capsule)
        total_raw = existing.raw_tokens + new_raw_tokens
        compressed_tokens = self._count(merged.render())

        updated = await self.store.update(
            existing.session_id,
            merged,
            mode=result.mode,
            raw_tokens=total_raw,
            compressed_tokens=compressed_tokens,
            reduction_pct=reduction_pct(total_raw, compressed_tokens),
            model=result.model,
            fallback_reason=result.fallback_reason,
            source_files=[f["name"] for f in ingestion["files"]],
            note=note,
        )

        added = merged.item_count - existing.capsule.item_count
        payload = {
            "ok": True,
            "session_id": updated.session_id,
            "version": updated.version,
            "previous_version": existing.version,
            "mode": updated.mode,
            "items_added": max(0, added),
            "capsule": updated.capsule.model_dump(),
            "capsule_preview": updated.capsule.render(),
            "metrics": {
                "session_raw_tokens": new_raw_tokens,
                "cumulative_raw_tokens": total_raw,
                "compressed_tokens": compressed_tokens,
                "tokens_saved": updated.tokens_saved,
                "reduction_pct": updated.reduction_pct,
            },
            "ingestion": ingestion,
            "warnings": list(result.warnings),
            "summary": (
                f"Capsule {updated.session_id} updated to v{updated.version}: "
                f"{max(0, added)} new item(s), cumulative {total_raw:,} approx. "
                f"tokens compressed to {compressed_tokens:,} "
                f"({updated.reduction_pct}% reduction)."
            ),
        }
        if result.fallback_reason:
            payload["fallback_reason"] = result.fallback_reason
        return payload

    # ------------------------------------------------------------------
    # 7. search_capsules
    # ------------------------------------------------------------------
    async def search_capsules(self, query: str, limit: int = 20) -> dict:
        if not (query or "").strip():
            raise InvalidInputError("query is required.")

        records = await self.store.search(query.strip(), limit=limit)
        matches = []
        for record in records:
            matches.append({**record.summary(), "excerpt": self._excerpt(record, query)})

        return {
            "ok": True,
            "query": query,
            "count": len(matches),
            "capsules": matches,
            "summary": (
                f"{len(matches)} capsule(s) match '{query}'."
                if matches
                else f"No capsules match '{query}'."
            ),
        }

    @staticmethod
    def _excerpt(record: CapsuleRecord, query: str, width: int = 140) -> str:
        """A short window of capsule text around the first match."""
        text = record.capsule.render()
        position = text.lower().find(query.strip().lower())
        if position == -1:
            return record.capsule.next_objective or text[:width]
        start = max(0, position - width // 2)
        snippet = text[start : start + width].replace("\n", " ").strip()
        return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(text) else "")

    # ------------------------------------------------------------------
    # 8. export_capsule
    # ------------------------------------------------------------------
    async def export_capsule(
        self,
        session_id: str,
        format: str = "txt",
        destination: Optional[str] = None,
    ) -> dict:
        """Write a capsule to disk as .txt (paste anywhere) or .json (tooling)."""
        fmt = (format or "txt").strip().lower().lstrip(".")
        if fmt not in EXPORT_FORMATS:
            raise InvalidInputError(
                f"Unknown export format '{format}'. Valid formats: {', '.join(EXPORT_FORMATS)}."
            )

        record = await self.store.get(session_id)
        if record is None:
            raise CapsuleNotFoundError(f"No capsule with id '{session_id}'.")

        if fmt == "txt":
            content = record.capsule.to_restore_prompt(
                record.session_id,
                created_at=record.created_at,
                mode=record.mode,
                version=record.version,
            )
        else:
            content = json.dumps(
                json.loads(record.model_dump_json()), indent=2, ensure_ascii=False
            )

        if destination:
            target = expand(destination)
            if target.is_dir():
                target = target / f"{record.session_id}_v{record.version}.{fmt}"
            ensure_parent_dir(target)
        else:
            target = (
                ensure_dir(self.settings.exports_path)
                / f"{record.session_id}_v{record.version}.{fmt}"
            )

        target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "session_id": record.session_id,
            "format": fmt,
            "path": str(target),
            "bytes_written": len(content.encode("utf-8")),
            "content": content,
            "summary": (
                f"Exported capsule {record.session_id} (v{record.version}) as "
                f"{fmt.upper()} to {target}."
            ),
        }

    # ------------------------------------------------------------------
    # Extras used by the transports
    # ------------------------------------------------------------------
    async def capsule_versions(self, session_id: str) -> dict:
        versions = await self.store.versions(session_id)
        return {
            "ok": True,
            "session_id": session_id,
            "count": len(versions),
            "versions": [
                {
                    "version": v.version,
                    "created_at": v.created_at,
                    "mode": v.mode,
                    "note": v.note,
                    "next_objective": v.capsule.next_objective,
                }
                for v in versions
            ],
        }

    async def health(self) -> dict:
        """Server self-check, used by the REST layer and by diagnostics."""
        await self.store.initialize()
        return {
            "ok": True,
            "version": __import__("contextslim").__version__,
            "database_path": str(self.settings.database_path),
            "export_dir": str(self.settings.exports_path),
            "deep_mode_available": self.settings.deep_mode_available,
            "deep_provider": self.deep.provider.describe(),
            "markitdown_available": self.ingestor.markitdown_available,
            "capsules_stored": await self.store.count(),
            "modes": MODE_DESCRIPTIONS,
        }


_service: Optional[ContextSlimService] = None


def get_service(settings: Optional[Settings] = None) -> ContextSlimService:
    """Return the process-wide service instance."""
    global _service
    if _service is None or settings is not None:
        _service = ContextSlimService(settings)
    return _service


def reset_service() -> None:
    """Drop the cached service (used by tests)."""
    global _service
    _service = None
