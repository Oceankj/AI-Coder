"""A valid provider reply may still fail the role's application schema."""

from dataclasses import replace
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from google.genai.models import AsyncModels
from scripted_gemini import ScriptedGemini

from ai_coder.main import create_app
from ai_coder.models import RunContext


@pytest.mark.parametrize("valid_on_retry", [True, False])
def test_plan_schema_recovers_once_or_checkpoints(settings, monkeypatch, valid_on_retry):
    provider = ScriptedGemini()
    planner_turns = []
    raw_marker = "do not persist invalid reply body"
    malformed = json.dumps({"spec": raw_marker, "features": []})

    def generate(*, contents, config, model):
        if not config.system_instruction.startswith("Planner."):
            return provider(contents=contents, config=config, model=model)
        planner_turns.append(contents)
        if len(planner_turns) == 2:
            assert contents[-2].parts[0].text == malformed
            assert "exact fields and value types" in contents[-1].parts[0].text
            assert '"features"' in config.system_instruction
            if valid_on_retry:
                return provider(contents=contents, config=config, model=model)
        return types.GenerateContentResponse(candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text=malformed)])),
        ])

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Role schema correction"}).json()["id"]
        run = client.portal.call(app.state.runs.start, workspace, "Build an adder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        result = app.state.storage.get_run(workspace, run.id)
        events = app.state.storage.list_events(RunContext(workspace, run.id))
        assert len(planner_turns) == 2
        retries = [event for event in events if event.type == "schema_retry"]
        assert len(retries) == 1 and "unreadable Plan" in retries[0].message
        assert all(raw_marker not in event.message for event in events)
        if valid_on_retry:
            assert result.status == "completed", result.error
            assert result.checks.tests == "passed"
        else:
            assert result.status == "blocked", result.error
            assert result.continuation["resume_node"] == "plan"
            assert result.error == "The agent returned an unreadable plan or diagnosis."
