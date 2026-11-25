"""A rejected parallel call must not lose the admitted sibling results."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from google.genai.models import AsyncModels
from scripted_gemini import ScriptedGemini

from ai_coder.main import create_app
from ai_coder.models import AgentRole, RunContext


@pytest.mark.parametrize("admit_writes", [True, False])
def test_parallel_tool_budget_finishes_admitted_siblings(settings, monkeypatch, admit_writes):
    provider = ScriptedGemini()
    monkeypatch.setattr("ai_coder.agents.runtime.MAX_AGENT_TOOL_CALLS", 2)
    coder_turns = 0

    def generate(**kwargs):
        nonlocal coder_turns
        if not kwargs["config"].system_instruction.startswith("Coder."):
            return provider(**kwargs)
        coder_turns += 1
        if coder_turns > 1:
            pytest.fail("A rejected tool call cannot allow another model turn.")
        add = provider.tool("writeFile", {"path": "add.cjs", "content": "exports.add = (a, b) => a + b;\n"})
        if admit_writes:
            notes = provider.tool("writeFile", {"path": "README.md", "content": "Adder example.\n"})
            rejected = provider.tool("writeFile", {"path": "unexpected.js", "content": "Denied at cap.\n"})
            parts = [add, notes, rejected]
        else:
            parts = [provider.tool("listFiles", {}), provider.tool("listFiles", {}), add]
        return types.GenerateContentResponse(candidates=[
            types.Candidate(content=types.Content(role="model", parts=parts)),
        ])

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Concurrent tool budget"}).json()["id"]
        run = client.portal.call(app.state.runs.start, workspace, "Build an adder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        context = RunContext(workspace, run.id)
        result = app.state.storage.get_run(workspace, run.id)
        events = [event for event in app.state.storage.list_events(context) if event.role == AgentRole.CODER]
        assert sum(event.type == "tool_call" for event in events) == 2
        assert sum(event.type == "tool_result" and event.message.endswith("completed") for event in events) == 2
        assert coder_turns == 1
        files = {file.path for file in app.state.storage.list_project_files(context)}
        if admit_writes:
            assert files == {"add.cjs", "add.test.js", "README.md"}
            assert result.status == "completed", result.error
            assert result.checks.tests == "passed"
            task = app.state.storage.get_current_task(context, AgentRole.CODER)
            assert set(task.result.artifact_paths) == {"add.cjs", "README.md"}
            assert any(event.type == "agent_interrupted" and "exceeded 2 tool calls" in event.message for event in events)
        else:
            assert files == {"add.test.js"}
            assert result.status == "blocked"
            assert result.error == "Agent exceeded 2 tool calls in one step."
            assert result.continuation["resume_node"] == "code"
