# Author: Ching Kao
# Student ID: 85768427
"""HTTP middleware registration: CORS and request diagnostics."""
import asyncio
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ai_coder.config import Settings
from ai_coder.storage.records import JsonlRecords


def install_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
        expose_headers=["Content-Disposition", "X-Request-ID", "Server-Timing"],
    )
    _install_chat_records(app, settings.chat_record_path)


def _install_chat_records(app: FastAPI, path: Path) -> None:
    record = JsonlRecords(path).write

    @app.middleware("http")
    async def chat_request_record(request: Request, call_next):
        if request.method != "POST" or request.url.path.rstrip("/") != "/api/chat":
            return await call_next(request)
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        common = {"requestId": request_id, "method": "POST", "path": "/api/chat"}
        await record({**common, "event": "started"})
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["Server-Timing"] = f"chat;dur={(perf_counter() - started) * 1000:.2f}"
            return response
        except asyncio.CancelledError:
            status = 499
            raise
        finally:
            fields = {}
            error_code = getattr(request.state, "chat_error_code", None)
            if error_code:
                fields["errorCode"] = error_code
            if status == 400:
                fields.setdefault("errorCode", "INVALID_INPUT")
            elif status >= 500:
                fields.setdefault("errorCode", "INTERNAL_ERROR")
            await record({**common, "event": "completed" if status < 400 else "failed",
                          "status": status, "durationMs": round((perf_counter() - started) * 1000, 2), **fields})
