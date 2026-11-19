"""Application composition root.

Run the development server from the backend/ directory:

    .venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000

`create_app` is a factory so tests can pass their own settings (for example a
temporary workspaces directory) without touching real data.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_coder.api.errors import install_error_handlers
from ai_coder.api.routes import router
from ai_coder.config import Settings, load_settings
from ai_coder.storage.repository import FileStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    app = FastAPI(title="AI Coder API", version="0.1.0")
    app.state.settings = settings
    # One storage instance per app, shared by every route (and, from step 4,
    # by the orchestrator), so its per-run locks protect all writers.
    app.state.storage = FileStorage(settings.workspaces_root)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
        # The download response names its ZIP file in this header; browsers
        # hide it from JavaScript unless it is exposed explicitly.
        expose_headers=["Content-Disposition"],
    )
    install_error_handlers(app)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness check used to confirm the frontend can reach the backend."""
        return {"status": "ok"}

    app.include_router(router)
    return app
