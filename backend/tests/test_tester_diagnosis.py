"""Tester diagnosis may inspect tests but cannot access implementation."""

from dataclasses import replace
import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from google.genai import types
from google.genai.models import AsyncModels
from scripted_gemini import ScriptedGemini

from ai_coder.main import create_app
from ai_coder.models import RunContext


def test_tester_diagnoses_fixture_mismatch_with_read_only_test_access(settings, monkeypatch):
    provider = ScriptedGemini()
    provider.spec = {
        "spec": "Implement lastModified passthrough using the add export of add.cjs.",
        "features": [{"title": "Folder reconnect", "criteria": ["Preserve the file's lastModified value"]}],
    }
    fixture_timestamp = 1700000000000
    implementation_marker = "implementation content is not exposed to Tester"
    writes, failed_turns, passing_turns = 0, 0, 0

    def test_source(expected):
        return (
            "const test = require('node:test');\n"
            "const assert = require('node:assert/strict');\n"
            "test('reconnects the local folder', () => {\n"
            f"  const file = {{ lastModified: {fixture_timestamp} }};\n"
            f"  assert.equal(require('./add.cjs').add(file), {expected});\n"
            "});\n"
        )

    def generate(*, contents, config, model):
        nonlocal writes, failed_turns, passing_turns
        prompt = config.system_instruction
        last = contents[-1].parts[0]
        if prompt.startswith("Tester author.") and not last.function_response:
            writes += 1
            if writes == 2:
                task = json.loads(last.text)
                assert task["assessment"]["decision"] == "test_invalid"
                assert "including files for earlier features" in prompt
                assert "Use a separate test file" not in prompt
                assert "Test the current feature." not in prompt
                expected = fixture_timestamp
            else:
                assert "Test the current feature." in prompt
                assert "Use a separate test file" in prompt
                expected = 9
            part = provider.tool("writeFile", {"path": "folder.test.js", "content": test_source(expected)})
        elif prompt.startswith("Coder.") and not last.function_response:
            part = provider.tool("writeFile", {
                "path": "add.cjs",
                "content": f"// {implementation_marker}\nexports.add = file => file.lastModified;\n",
            })
        elif prompt.startswith("Tester diagnosis (Green)."):
            failed_turns += 1
            assert {decl.name for decl in config.tools[0].function_declarations} == {"listFiles", "readFile"}
            if failed_turns == 1:
                task = json.loads(last.text)
                assert task["execution"]["outcome"] == "failed"
                assert task["existingTestFiles"] == ["folder.test.js"]
                part = provider.tool("readFile", {"path": "folder.test.js"})
            else:
                assert last.function_response.name == "readFile"
                content = last.function_response.response["result"]
                if failed_turns == 2:
                    assert f"lastModified: {fixture_timestamp}" in content
                    assert ".add(file), 9" in content
                    part = provider.tool("readFile", {"path": "add.cjs"})
                else:
                    assert failed_turns == 3
                    assert "may not read 'add.cjs'" in content
                    assert implementation_marker not in content
                    part = types.Part(text=json.dumps({
                        "decision": "test_invalid",
                        "reason": f"The fixture contains lastModified {fixture_timestamp}, but the assertion expects 9.",
                    }))
        else:
            if prompt.startswith("Tester diagnosis (Red)."):
                passing_turns += 1
                assert not config.tools
                assert json.loads(last.text)["execution"]["outcome"] == "passed"
            return provider(contents=contents, config=config, model=model)
        return types.GenerateContentResponse(candidates=[
            types.Candidate(content=types.Content(role="model", parts=[part])),
        ])

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture", max_repairs=0))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Read-only diagnosis"}).json()["id"]
        run = client.portal.call(app.state.runs.start, workspace, "Reconnect a local audio folder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        context = RunContext(workspace, run.id)
        paused = app.state.storage.get_run(workspace, run.id)
        assert paused.status == "blocked"
        assert paused.error.startswith("Repair budget exhausted.")
        assert paused.continuation["resume_node"] == "tests"
        assert paused.continuation["assessment"]["decision"] == "test_invalid"
        client.portal.call(app.state.runs.resume, context, "Correct the faulty fixture assertion.")
        client.portal.call(app.state.scheduler.wait_idle)
        final = app.state.storage.get_run(workspace, run.id)
        assert final.status == "completed", final.error
        assert (writes, failed_turns, passing_turns) == (2, 3, 1)
        messages = [event.message for event in app.state.storage.list_events(context)]
        assert "tester → readFile: completed" in messages
        assert "tester → readFile: failed" in messages
        checks = app.state.storage.list_check_executions(context)
        assert [check.outcome for check in checks] == ["failed", "failed", "passed"]
