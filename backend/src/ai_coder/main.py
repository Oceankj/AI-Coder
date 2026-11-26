# Author: Ching Kao
# Student ID: 85768427
"""Application composition root.

Run the development server from the backend/ directory:

    .venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000

`create_app` is a factory so tests can pass their own settings for isolated storage.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_coder.orchestration.tdd import TDDWorkflow
from ai_coder.orchestration.runs import RunService
from ai_coder.api.errors import install_error_handlers
from ai_coder.api.routes import router
from ai_coder.api.chat import router as chat_router
from ai_coder.api.records import router as records_router
from ai_coder.api.middleware import install_middleware
from ai_coder.llm.codex import CodexAdapter
from ai_coder.llm.gemini import GeminiAdapter
from ai_coder.llm.gateway import LLMGateway
from ai_coder.storage.records import JsonlRecords
from ai_coder.llm.groq import GroqAdapter
from ai_coder.config import Provider, Settings, load_settings
from ai_coder.orchestration.scheduler import RunScheduler
from ai_coder.storage.repository import FileStorage

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API and its TDD workflow."""
    settings = settings or load_settings()
    # One storage instance per app, shared by the routes and the orchestrator,
    # so its per-run locks protect every writer in this process.
    storage = FileStorage(settings.workspaces_root)
    codex = CodexAdapter(executable=settings.codex_executable, model=settings.codex_model,
                         timeout_seconds=settings.codex_timeout_seconds, transport=settings.codex_transport)
    llm = LLMGateway({
        Provider.GEMINI: GeminiAdapter(api_key=settings.gemini_api_key, model=settings.gemini_model,
                                     timeout_seconds=settings.gemini_timeout_seconds),
        Provider.GROQ: GroqAdapter(api_key=settings.groq_api_key, model=settings.groq_model,
                                  timeout_seconds=settings.groq_timeout_seconds),
        Provider.CODEX: codex,
    }, JsonlRecords(settings.llm_record_path))
    workflow = TDDWorkflow(storage, llm, settings)
    scheduler = RunScheduler(workflow)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Runs that were queued or running when the backend last stopped can
        # never finish now; mark them failed so the UI does not wait forever.
        recovered = storage.fail_interrupted_runs()
        if recovered:
            logger.warning("Marked %d interrupted run(s) as failed", len(recovered))
        try:
            yield
        finally:
            try:
                await scheduler.shutdown()
            finally:
                await codex.close()

    app = FastAPI(title="AI Coder API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.scheduler = scheduler
    app.state.llm = llm
    app.state.runs = RunService(storage, scheduler)

    install_error_handlers(app)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness check used to confirm the frontend can reach the backend."""
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(chat_router)
    app.include_router(records_router)
    install_middleware(app, settings)
    return app
