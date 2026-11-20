"""Application composition root.

Run the development server from the backend/ directory:

    .venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000

`create_app` is a factory so tests can pass their own settings (for example a
temporary workspaces directory) and their own agents, without touching real
data.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_coder.agents.base import Agent
from ai_coder.agents.placeholder import placeholder_agents
from ai_coder.api.errors import install_error_handlers
from ai_coder.api.routes import router
from ai_coder.config import Settings, load_settings
from ai_coder.models import AgentRole
from ai_coder.orchestration.orchestrator import Orchestrator
from ai_coder.orchestration.scheduler import RunScheduler
from ai_coder.storage.repository import FileStorage

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    agents: Mapping[AgentRole, Agent] | None = None,
) -> FastAPI:
    """Build the API.

    `agents` defaults to the placeholder agents. Stage 4 passes the real
    Gemini agents here (one per role).
    """
    settings = settings or load_settings()
    # One storage instance per app, shared by the routes and the orchestrator,
    # so its per-run locks protect every writer in this process.
    storage = FileStorage(settings.workspaces_root)
    if agents is None:
        agents = placeholder_agents(
            storage,
            delay_seconds=settings.placeholder_delay_seconds,
            test_failures=settings.placeholder_test_failures,
        )
    orchestrator = Orchestrator(
        storage,
        agents,
        max_repairs=settings.max_repairs,
        max_features=settings.max_features,
        agent_timeout_seconds=settings.agent_timeout_seconds,
    )
    scheduler = RunScheduler(orchestrator)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Runs that were queued or running when the backend last stopped can
        # never finish now; mark them failed so the UI does not wait forever.
        recovered = storage.fail_interrupted_runs()
        if recovered:
            logger.warning("Marked %d interrupted run(s) as failed", len(recovered))
        yield
        await scheduler.shutdown()

    app = FastAPI(title="AI Coder API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.scheduler = scheduler

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
