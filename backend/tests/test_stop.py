"""Stop requests cancel the scoped work and keep its generated files."""

import asyncio
import json
from dataclasses import replace

from fastapi.testclient import TestClient
from google.genai.models import AsyncModels

from ai_coder.main import create_app
from ai_coder.models import RunContext


def test_stop_cancels_running_and_queued_runs_without_touching_another_workspace(settings, monkeypatch):
    started, cancelled = asyncio.Queue(), []

    async def model(*args, **kwargs):
        number = started.qsize()
        started.put_nowait(True)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(number)

    monkeypatch.setattr(AsyncModels, "generate_content", model)
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        storage, runs = app.state.storage, app.state.runs
        workspace = storage.create_workspace("Selected").id
        other = storage.create_workspace("Other").id
        active = client.portal.call(runs.start, workspace, "Work", [])
        client.portal.call(asyncio.wait_for, started.get(), 3)
        queued = client.portal.call(runs.start, workspace, "Wait", [])
        separate = client.portal.call(runs.start, other, "Other work", [])
        client.portal.call(asyncio.wait_for, started.get(), 3)
        project = storage.project_dir(RunContext(workspace, active.id))
        saved = project / "already-written.js"
        saved.write_text("export const answer = 42;\n")

        assert client.post(f"/api/workspaces/{other}/runs/{active.id}/stop").status_code == 404
        for run in (queued, active):
            path = f"/api/workspaces/{workspace}/runs/{run.id}"
            response = client.post(path + "/stop")
            assert response.status_code == 200, response.text
            result = response.json()
            assert (result["status"], result["activeRole"], result["error"]) == ("stopped", None, None)
            assert client.post(path + "/stop").json()["status"] == "stopped"
            assert client.get(path).json()["status"] == "stopped"
            events = storage.list_events(RunContext(workspace, run.id))
            assert sum(event.type == "stopped" for event in events) == 1
        assert len(cancelled) == 1
        assert storage.get_run(other, separate.id).status == "running"
        assert saved.read_text() == "export const answer = 42;\n"


def test_chat_connection_abort_cancels_the_backend_reply(settings, monkeypatch):
    async def exercise():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def coordinate(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr("ai_coder.api.chat.coordinate", coordinate)
        app = create_app(settings)
        inbound = asyncio.Queue()
        inbound.put_nowait({"type": "http.request", "body": json.dumps({
            "messages": [{"role": "user", "content": "Start a reply"}],
        }).encode(), "more_body": False})

        async def send(message):
            pass

        request = asyncio.create_task(app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/api/chat",
            "raw_path": b"/api/chat", "root_path": "", "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
        }, inbound.get, send))
        try:
            await asyncio.wait_for(started.wait(), 3)
            inbound.put_nowait({"type": "http.disconnect"})
            await asyncio.wait_for(asyncio.shield(request), 3)
            assert cancelled.is_set()
            log = json.loads(settings.chat_record_path.read_text().splitlines()[-1])
            assert log["status"] == 499
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)

    asyncio.run(exercise())
