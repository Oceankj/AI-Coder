# Author: Ching Kao
# Student ID: 85768427
"""Coordinator run tools use actual workspace evidence and retry the selected run."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from ai_coder.agents import coordinator
from ai_coder.config import Provider


@pytest.mark.parametrize("provider", list(Provider))
def test_start_run_persists_original_user_messages_for_every_provider(client, monkeypatch, provider):
    """Exercise HTTP → Coordinator → RunService → storage without starting workers."""
    submitted = []
    monkeypatch.setattr(client.app.state.scheduler, "submit", submitted.append)
    workspace_id = client.post("/api/workspaces", json={"name": "Requirements"}).json()["id"]
    requirements = ["Use the selected test runner"]

    async def fake_invoke(model, prompt, messages, tools, timeout):
        assert model.provider == provider
        result = await tools[0].ainvoke({"description": "Build a playlist", "requirements": requirements})
        return [AIMessage(content=result, response_metadata={
            "usage": {"apiCalls": 1, "inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "model": "fixture", "resolvedModel": "fixture", "timing": {},
        })]

    monkeypatch.setattr(coordinator, "invoke", fake_invoke)
    response = client.post("/api/chat", json={
        "workspaceId": workspace_id, "provider": provider,
        "messages": [
            {"role": "user", "content": "Build a playlist using Node tests."},
            {"role": "assistant", "content": "Should I use Jest?"},
            {"role": "user", "content": "Use node --test, not Jest.\nKeep genre filtering."},
        ],
    })
    assert response.status_code == 200, response.text
    run = client.app.state.storage.get_run(workspace_id, response.json()["runId"])
    assert run.provider == provider
    assert run.input.requirements == [
        "Use the selected test runner",
        "Original user messages (latest clarification takes precedence):\n"
        "Build a playlist using Node tests.\n\nUse node --test, not Jest.\nKeep genre filtering.",
    ]
    assert requirements == ["Use the selected test runner"]
    assert len(submitted) == 1 and submitted[0].run_id == run.id


def test_run_tools_report_manifest_and_retry_latest_blocked_run(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text('{"scripts":{"test":"jest"}}')
    run = SimpleNamespace(
        id="run-1", status="blocked", active_role=None, error="npm install failed (exit 1)",
        coordinator_report="Installation failed.", checks=SimpleNamespace(to_json=lambda: {"tests": "not_run"}),
    )
    submitted = []

    def resume(context, clarification):
        submitted.append((context.workspace_id, context.run_id, clarification))
        return SimpleNamespace(id=run.id, status="queued")

    storage = SimpleNamespace(
        list_runs=lambda workspace_id: [run],
        get_run=lambda workspace_id, run_id: run if run_id == run.id else None,
        project_dir=lambda context: project,
    )
    app = SimpleNamespace(
        runs=SimpleNamespace(storage=storage, resume=resume), llm=object(),
        settings=SimpleNamespace(agent_timeout_seconds=10),
    )
    body = SimpleNamespace(
        workspaceId="workspace-1", runId=None, provider=Provider.GEMINI,
        messages=[SimpleNamespace(role="user", content="Try npm install again")],
    )

    async def fake_invoke(model, prompt, messages, tools, timeout):
        assert "Call getRun before explaining a run failure" in prompt
        result = await tools[1].ainvoke({})
        assert result["packageJsonExists"] is True
        assert result["reason"] == "npm install failed (exit 1)"
        assert await tools[2].ainvoke({"clarification": messages[-1][1]}) == "Resumed development run run-1."
        return [AIMessage(
            content="Resumed development run run-1.",
            response_metadata={
                "usage": {"apiCalls": 1, "inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "model": "fixture", "resolvedModel": "fixture", "timing": {},
            },
        )]

    monkeypatch.setattr(coordinator, "invoke", fake_invoke)
    response = asyncio.run(coordinator.coordinate(app, body, "request-1"))
    assert response["runId"] == "run-1"
    assert response["status"] == "queued"
    assert submitted == [("workspace-1", "run-1", "Try npm install again")]
