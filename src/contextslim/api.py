"""Optional FastAPI surface over the same service layer.

MCP is the product: this exists for the cases MCP cannot reach - a Cursor
plugin, a CI job, an agent framework, or a quick curl during a demo. Because
both transports call :class:`~contextslim.service.ContextSlimService`, they
cannot drift apart in behaviour.

Run it with::

    uvicorn contextslim.api:app --reload
    python -m contextslim.api
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .errors import (
    CapsuleNotFoundError,
    ContextSlimError,
    IngestionError,
    InvalidInputError,
    RateLimitedError,
)
from .service import ContextSlimService, get_service

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR = {
    CapsuleNotFoundError: 404,
    InvalidInputError: 400,
    IngestionError: 422,
    RateLimitedError: 429,
}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ExtractRequest(BaseModel):
    chat_history: Optional[str] = Field(default=None, description="Raw conversation text.")
    mode: str = Field(default="slim", description="'slim' or 'deep'.")
    project: Optional[str] = None
    title: Optional[str] = None
    file_paths: Optional[List[str]] = Field(
        default=None, description="Documents to ingest alongside the chat."
    )


class UpdateRequest(BaseModel):
    chat_history: Optional[str] = None
    mode: str = "slim"
    note: Optional[str] = None
    file_paths: Optional[List[str]] = None


class HealthCheckRequest(BaseModel):
    token_count: Optional[int] = None
    chat_history: Optional[str] = None


class ExportRequest(BaseModel):
    format: str = Field(default="txt", description="'txt' or 'json'.")
    destination: Optional[str] = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app(service: Optional[ContextSlimService] = None) -> FastAPI:
    """Build the API. Passing a service makes the app trivially testable."""
    app = FastAPI(
        title="ContextSlim AI",
        version=__import__("contextslim").__version__,
        description=(
            "REST surface over ContextSlim's session-state engine. The primary "
            "interface is the MCP server; this exists for non-MCP callers."
        ),
    )

    def provide_service() -> ContextSlimService:
        return service or get_service()

    @app.exception_handler(ContextSlimError)
    async def handle_contextslim_error(_: Request, exc: ContextSlimError) -> JSONResponse:
        status = next(
            (code for kind, code in _STATUS_BY_ERROR.items() if isinstance(exc, kind)), 400
        )
        return JSONResponse(
            status_code=status,
            content={"ok": False, "error": {"code": exc.code, "message": str(exc)}},
        )

    # -- diagnostics ----------------------------------------------------
    @app.get("/health", tags=["diagnostics"])
    async def health(svc: ContextSlimService = Depends(provide_service)) -> dict:
        return await svc.health()

    @app.get("/stats", tags=["analytics"])
    async def stats(svc: ContextSlimService = Depends(provide_service)) -> dict:
        return await svc.get_stats()

    # -- context health -------------------------------------------------
    @app.post("/context/health", tags=["session state"])
    async def context_health(
        payload: HealthCheckRequest, svc: ContextSlimService = Depends(provide_service)
    ) -> dict:
        return svc.check_context_health(
            token_count=payload.token_count, chat_history=payload.chat_history
        )

    # -- capsules -------------------------------------------------------
    @app.post("/capsules", status_code=201, tags=["session state"])
    async def extract(
        payload: ExtractRequest, svc: ContextSlimService = Depends(provide_service)
    ) -> dict:
        return await svc.extract_session_state(**payload.model_dump())

    @app.get("/capsules", tags=["session state"])
    async def list_capsules(
        limit: int = Query(default=20, ge=1, le=200),
        project: Optional[str] = None,
        svc: ContextSlimService = Depends(provide_service),
    ) -> dict:
        return await svc.list_capsules(limit=limit, project=project)

    # Declared before /capsules/{session_id} so "search" is not read as an id.
    @app.get("/capsules/search", tags=["session state"])
    async def search(
        q: str = Query(..., min_length=1, description="Keyword to search for."),
        limit: int = Query(default=20, ge=1, le=200),
        svc: ContextSlimService = Depends(provide_service),
    ) -> dict:
        return await svc.search_capsules(query=q, limit=limit)

    @app.get("/capsules/{session_id}", tags=["session state"])
    async def load(
        session_id: str, svc: ContextSlimService = Depends(provide_service)
    ) -> dict:
        return await svc.load_capsule(session_id)

    @app.patch("/capsules/{session_id}", tags=["session state"])
    async def update(
        session_id: str,
        payload: UpdateRequest,
        svc: ContextSlimService = Depends(provide_service),
    ) -> dict:
        return await svc.update_capsule(session_id=session_id, **payload.model_dump())

    @app.get("/capsules/{session_id}/versions", tags=["session state"])
    async def versions(
        session_id: str, svc: ContextSlimService = Depends(provide_service)
    ) -> dict:
        return await svc.capsule_versions(session_id)

    @app.post("/capsules/{session_id}/export", tags=["session state"])
    async def export(
        session_id: str,
        payload: ExportRequest,
        svc: ContextSlimService = Depends(provide_service),
    ) -> dict:
        return await svc.export_capsule(
            session_id=session_id, format=payload.format, destination=payload.destination
        )

    return app


app = create_app()


def main() -> None:  # pragma: no cover - exercised manually
    """Run the REST API with uvicorn."""
    import uvicorn

    settings = get_settings()
    settings.ensure_runtime_dirs()
    uvicorn.run(
        "contextslim.api:app",
        host="127.0.0.1",
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
