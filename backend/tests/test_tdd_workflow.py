# Author: Ching Kao
# Student ID: 85768427
"""Run the production graph with real stdio MCP and Node, replacing only Google."""

import asyncio
import io
import json
from dataclasses import replace
from zipfile import ZipFile
from unittest.mock import AsyncMock

import pytest
from google.genai.models import AsyncModels

from fastapi.testclient import TestClient
from scripted_gemini import ScriptedGemini

from ai_coder.main import create_app


def chat(client, workspace, text, **context):
    response = client.post(
        "/api/chat",
        json={"workspaceId": workspace, **context, "messages": [{"role": "user", "content": text}]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_chat_to_verified_download(settings, monkeypatch):
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=ScriptedGemini(block=True)))
    app = create_app(replace(settings, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "TDD integration"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        base = f"/api/workspaces/{workspace}/runs/{run}"
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == "blocked", detail
        assert "numeric types" in detail["error"]
    # Restart between clarification turns to prove the checkpoint is durable.
    app = create_app(replace(settings, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        assert chat(client, workspace, "Use integers", runId=run)["runId"] == run
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == "completed", detail
        assert detail["checks"]["tests"] == "passed"
        assert "completed" in chat(client, workspace, "progress", runId=run)["message"]["content"]
        assert len(client.get(f"/api/workspaces/{workspace}/runs").json()) == 1
        directory = settings.workspaces_root / workspace / "runs" / run
        assert (directory / "artifacts" / f"{run}.zip").is_file()
        checks = json.loads((directory / "checks.json").read_text())["executions"]
        assert [c["outcome"] for c in checks] == ["failed", "failed", "failed", "passed"]
        assert [c["passed"] for c in checks] == [0, 0, 0, 1]
        assert "MODULE_NOT_FOUND" in checks[0]["log"]
        assert "0 !== 3" in checks[-2]["log"]
        calls = [json.loads(line) for line in settings.llm_record_path.read_text().splitlines()]
        run_calls = [c for c in calls if c.get("runId") == run and c["event"] == "completed"]
        assert {c["role"] for c in run_calls} == {"planner", "tester", "coder", "coordinator"}
        assert detail["usage"]["apiCalls"] == len(run_calls)
        assert detail["coordinatorReport"] and "All required tests passed" in detail["coordinatorReport"]
        events = client.get(base + "/events").json()["events"]
        assert {e["role"] for e in events if e["type"] == "role_started"} == {"planner", "tester", "coder"}
        assert all(e["role"] in {"tester", "coder"} for e in events if e["type"] == "tool_call")
        assert all("role" not in e for e in events if e["type"] == "checks")
        assert any(e["type"] == "diagnosis" and "implementation_defect" in e["message"] for e in events)
        with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archive:
            assert {"add.cjs", "add.test.js"} <= set(archive.namelist())


@pytest.mark.parametrize(
    "max_repairs, second_feature, expected_status", [(0, False, "blocked"), (3, True, "completed")]
)
def test_repair_limit_and_feature_routing(
    settings, monkeypatch, max_repairs, second_feature, expected_status
):
    provider = ScriptedGemini(second_feature=second_feature)
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=provider))
    app = create_app(replace(settings, max_repairs=max_repairs, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "TDD routing"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        base = f"/api/workspaces/{workspace}/runs/{run}"
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == expected_status, detail
        events = client.get(base + "/events").json()["events"]
        if expected_status == "blocked":
            assert "Repair budget exhausted" in detail["error"]
            assert provider.implementations == 1
            assert client.get(base + "/download").status_code == 409
        else:
            directory = settings.workspaces_root / workspace / "runs" / run
            tasks = json.loads((directory / "tasks.json").read_text())["tasks"]
            assert sum(t["role"] == "planner" for t in tasks) == 1
            assert all(t["status"] == "submitted" for t in tasks)
            coder_tasks = [t for t in tasks if t["role"] == "coder"]
            assert [t["feature"]["number"] for t in coder_tasks] == [1, 1]
            assert all(t["plan"] == provider.spec["spec"] for t in coder_tasks)
            assert "0 !== 3" in coder_tasks[-1]["previousFailure"]
            diagnoses = [e["message"] for e in events if e["type"] == "diagnosis"]
            assert any("test_invalid" in d for d in diagnoses)
            assert any("already_passing" in d for d in diagnoses)
            assert [e["message"] for e in events if e["type"] == "feature_completed"] == [
                "Addition",
                "Adding zero",
            ]
            assert "2 passed, 0 failed" in [e["message"] for e in events if e["type"] == "checks"][-1]
            assert provider.implementations == 2


@pytest.mark.parametrize("titles,status", [([], "blocked"), (["   "], "blocked"), (["A", "B"], "failed")])
def test_invalid_plan_stops_before_implementation(settings, monkeypatch, titles, status):
    provider = ScriptedGemini()
    provider.spec["features"] = [{"title": title, "criteria": ["Returns 3"]} for title in titles]
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=provider))
    app = create_app(replace(settings, gemini_api_key="fixture", max_features=1))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Planning"}).json()["id"]
        base = f"/api/workspaces/{ws}/runs"
        run = client.portal.call(app.state.runs.start, ws, "Build an adder", []).id
        client.portal.call(app.state.scheduler.wait_idle)
        result = client.get(f"{base}/{run}").json()
        assert result["status"] == status and result["error"]
        assert result["activeRole"] is None and result["checks"]["tests"] == "not_run"
        assert provider.implementations == 0


def test_planner_timeout_releases_workspace_and_shutdown_cancels_next_run(settings, monkeypatch):
    async def exercise():
        started = asyncio.Queue()
        cancelled = []
        async def stalled(**kwargs):
            call = len(cancelled) + 1
            started.put_nowait(call)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(call)

        monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=stalled))
        app = create_app(replace(settings, agent_timeout_seconds=0.5, gemini_api_key="fixture"))
        storage, runs, scheduler = app.state.storage, app.state.runs, app.state.scheduler
        ws = storage.create_workspace("Scheduling").id
        first = runs.start(ws, "First", [])
        assert await asyncio.wait_for(started.get(), 10) == 1
        second = runs.start(ws, "Second", [])
        assert storage.get_run(ws, first.id).active_role.value == "planner"
        assert storage.get_run(ws, second.id).status == "queued"
        assert await asyncio.wait_for(started.get(), 10) == 2
        assert storage.get_run(ws, first.id).status == "failed"
        assert storage.get_run(ws, second.id).status == "running"
        await scheduler.shutdown()
        interrupted = storage.get_run(ws, second.id)
        assert interrupted.status == "failed" and interrupted.active_role is None
        assert cancelled == [1, 2]

    asyncio.run(exercise())


@pytest.mark.parametrize("case", ["no_test_file", "false_pass", "shared_budget"])
def test_unverified_feature_cannot_complete(settings, monkeypatch, case):
    provider = ScriptedGemini(second_feature=case == "shared_budget")

    def generate(**kwargs):
        reply = provider(**kwargs)
        part = reply.candidates[0].content.parts[0]
        phase = kwargs["config"].system_instruction
        if case == "no_test_file" and phase.startswith("Tester author."):
            part.function_call = None
            part.text = "All tests are ready."
        elif case == "false_pass" and phase.startswith("Tester diagnosis (Red)"):
            part.text = json.dumps({"decision": "already_passing", "reason": "Looks correct."})
        elif case == "shared_budget" and phase.startswith("Coder.") and part.function_call:
            # The first feature passes after repair. The zero case still fails.
            part.function_call.args["content"] = part.function_call.args["content"].replace(
                "a + b", "(b === 0 ? -1 : a + b)"
            )
        return reply

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture", max_repairs=2))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Evidence"}).json()["id"]
        run = chat(client, ws, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{ws}/runs/{run}"
        detail = client.get(base).json()
        assert detail["status"] == "blocked"
        assert detail["checks"]["tests"] == ("not_run" if case == "no_test_file" else "failed")
        assert client.get(base + "/download").status_code == 409
        if case == "shared_budget":
            assert "Repair budget exhausted" in detail["error"]
            events = client.get(base + "/events").json()["events"]
            assert [e["message"] for e in events if e["type"] == "feature_completed"] == ["Addition"]
        else:
            assert provider.implementations == 0
