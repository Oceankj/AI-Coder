# Author: Ching Kao
# Student ID: 85768427
"""Exercise the real gateway, agent graph and MCP through Groq's HTTP contract."""
import json
import io
from dataclasses import replace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_coder.main import create_app
from ai_coder.agents.runtime import MAX_AGENT_MODEL_CALLS


def reply(content=None, *, tool=None, arguments=None):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [{
            "type": "function", "id": f"call-{tool}",
            "function": {"name": tool, "arguments": json.dumps(arguments)},
        }]
    return httpx.Response(200, json={
        "model": "resolved-groq-model", "choices": [{"message": message}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    })


@pytest.mark.parametrize(("post_write_error", "expected_code"), [
    (httpx.Response(429, json={"error": {"message": "quota"}}), "GROQ_RATE_LIMIT"),
    (httpx.ReadTimeout("fixture timeout"), "GROQ_TIMEOUT"),
])
def test_workspace_chat_runs_red_green_via_groq(settings, monkeypatch, post_write_error, expected_code):
    source = "const test = require('node:test');\nconst assert = require('node:assert/strict');\ntest('adds', () => assert.equal(require('./add.cjs').add(1,2), 3));"
    transport = AsyncMock(side_effect=[
        reply(tool="startRun", arguments={"description": "Build an adder", "requirements": []}),
        reply(json.dumps({"spec": "Export add.", "features": [{"title": "Addition", "criteria": ["add(1,2) returns 3"]}]})),
        reply(json.dumps({"reason": "Node built-ins suffice.", "packages": {}})),
        reply(tool="writeFile", arguments={"path": "add.test.js", "content": source}),
        reply("Test file written."),
        reply(json.dumps({"decision": "expected_failure", "reason": "The add module is missing."})),
        reply(tool="writeFile", arguments={"path": "add.cjs", "content": "exports.add = (a,b) => a+b;"}),
        reply(tool="writeFile", arguments={"path": "index.html", "content": "<title>Addition</title>"}),
        post_write_error,
        reply(json.dumps({"decision": "approve", "reason": "The tests cover addition."})),
        reply("The addition test passed."),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, gemini_api_key="other-fixture"))
    with TestClient(app) as client:
        config = client.get("/api/chat/config?provider=groq").json()
        assert config == {"provider": "groq", "configured": False, "model": settings.groq_model}
        assert client.get("/api/chat/config?provider=gemini").json()["configured"]
        credentials = {"provider": "groq", "apiKey": "groq-fixture"}
        assert client.post("/api/chat/config", json=credentials).json()["configured"]
        ws = client.post("/api/workspaces", json={"name": "Groq integration"}).json()["id"]
        response = client.post("/api/chat", json={
            "provider": "groq", "workspaceId": ws, "messages": [{"role": "user", "content": "Build an adder"}],
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["usage"] == {"apiCalls": 1, "inputTokens": 8, "outputTokens": 4, "totalTokens": 12}
        base = f"/api/workspaces/{ws}/runs/{body['runId']}"
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert app.state.storage.get_run(ws, body["runId"]).provider == "groq"
        assert client.get("/api/chat/config").json()["provider"] == "gemini"
        assert detail["status"] == "completed", detail
        assert detail["checks"]["tests"] == "passed"
        events = client.get(base + "/events").json()["events"]
        assert len([event for event in events if event["type"] == "tool_result"
                    and event["message"] == "coder → writeFile: completed"]) == 2
        assert any(event["type"] == "agent_interrupted" and expected_code in event["message"]
                   for event in events)
        with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archive:
            assert {"add.test.js", "add.cjs", "index.html"} <= set(archive.namelist())
        assert detail["coordinatorReport"] == "The addition test passed."

    for call in transport.await_args_list:
        assert call.args == ("https://api.groq.com/openai/v1/chat/completions",)
        assert call.kwargs["headers"]["Authorization"] == "Bearer groq-fixture"
        payload = call.kwargs["json"]
        assert payload["model"] == settings.groq_model
        assert payload["messages"][0]["role"] == "system"
        for definition in payload.get("tools", []):
            assert definition["type"] == "function" and "parameters" in definition["function"]
        if payload["messages"][0]["content"].startswith("Architect environment."):
            assert "tools" not in payload
    records = [json.loads(row) for row in settings.llm_record_path.read_text().splitlines()]
    completed = [record for record in records if record["event"] == "completed"]
    assert len(completed) == transport.await_count - 1
    assert any(record["event"] == "failed" and record.get("errorCode") == expected_code for record in records)
    assert all(record["provider"] == "groq" and record["resolvedModel"] == "resolved-groq-model" for record in completed)
    assert {r.get("role") for r in completed} == {None, "coordinator", "planner", "architect", "tester", "coder"}


def test_groq_quota_error_is_recorded_without_raw_provider_body(settings, monkeypatch):
    transport = AsyncMock(return_value=httpx.Response(429, text="sensitive provider details"))
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"provider": "groq", "messages": [{"role": "user", "content": "hello"}]})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "GROQ_RATE_LIMIT"
    records = settings.llm_record_path.read_text()
    assert "sensitive provider details" not in records + response.text
    failure = json.loads(records.splitlines()[-1])
    assert (failure["event"], failure["provider"], failure["providerStatus"]) == ("failed", "groq", 429)


def test_groq_model_setting_drives_chat_and_rejects_unknown_models(settings, monkeypatch):
    transport = AsyncMock(return_value=reply("20b ready"))
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    with TestClient(app) as client:
        assert client.post("/api/chat/model", json={"model": "unknown/model"}).status_code == 400
        assert client.get("/api/chat/config?provider=groq").json()["model"] == "openai/gpt-oss-120b"
        changed = client.post("/api/chat/model", json={"model": "openai/gpt-oss-20b"})
        assert changed.status_code == 200
        assert changed.json() == {"provider": "groq", "configured": True, "model": "openai/gpt-oss-20b"}
        chat = client.post("/api/chat", json={"provider": "groq", "messages": [{"role": "user", "content": "Hello"}]})
        assert chat.status_code == 200
        assert chat.json()["model"] == "openai/gpt-oss-20b"
        assert transport.await_args.kwargs["json"]["model"] == "openai/gpt-oss-20b"
        assert client.get("/api/chat/config?provider=gemini").json()["model"] == settings.gemini_model


def test_tester_repeated_read_errors_stop_before_quota_is_drained(settings, monkeypatch):
    transport = AsyncMock(side_effect=[
        reply(tool="startRun", arguments={"description": "Build a todo app", "requirements": []}),
        reply(json.dumps({"spec": "Create index.html and todo tests.", "features": [
            {"title": "Todo", "criteria": ["Adding an item displays it."]},
        ]})),
        reply(json.dumps({"reason": "No packages needed.", "packages": {}})),
        *(reply(tool="readFile", arguments={"path": "index.html"}) for _ in range(3)),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture", groq_model="openai/gpt-oss-20b"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Read limit"}).json()["id"]
        started = client.post("/api/chat", json={
            "provider": "groq", "workspaceId": workspace,
            "messages": [{"role": "user", "content": "Build a todo app"}],
        })
        assert started.status_code == 200
        client.portal.call(app.state.scheduler.wait_idle)
        run = client.get(f"/api/workspaces/{workspace}/runs/{started.json()['runId']}").json()
        assert run["status"] == "blocked"
        assert "Tool calls failed 3 times" in run["error"]
        assert run["checks"]["tests"] == "not_run"
        assert transport.await_count == 6


def test_groq_rate_limit_before_any_test_file_keeps_run_resumable(settings, monkeypatch):
    transport = AsyncMock(side_effect=[
        reply(tool="startRun", arguments={"description": "Build a todo app", "requirements": []}),
        reply(json.dumps({"spec": "Create a todo app.", "features": [
            {"title": "Todo", "criteria": ["Adding an item displays it."]},
        ]})),
        reply(json.dumps({"reason": "No packages needed.", "packages": {}})),
        httpx.Response(429, json={"error": {"message": "quota"}}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Rate limit"}).json()["id"]
        started = client.post("/api/chat", json={
            "provider": "groq", "workspaceId": workspace,
            "messages": [{"role": "user", "content": "Build a todo app"}],
        })
        assert started.status_code == 200
        client.portal.call(app.state.scheduler.wait_idle)
        run_id = started.json()["runId"]
        detail = client.get(f"/api/workspaces/{workspace}/runs/{run_id}").json()
        assert detail["status"] == "blocked"
        assert detail["error"] == "Groq's quota or rate limit was reached."
        assert app.state.storage.get_run(workspace, run_id).continuation is not None
        assert transport.await_count == 4


def test_coordinator_repeated_successful_tool_calls_hit_step_limit(settings, monkeypatch):
    transport = AsyncMock(return_value=reply(tool="getRun", arguments={}))
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Loop guard"}).json()["id"]
        response = client.post("/api/chat", json={
            "provider": "groq", "workspaceId": workspace,
            "messages": [{"role": "user", "content": "Progress?"}],
        })
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AGENT_STEP_LIMIT"
        assert transport.await_count == MAX_AGENT_MODEL_CALLS


def test_groq_invalid_tool_call_is_distinguished_from_bad_request(settings, monkeypatch):
    transport = AsyncMock(return_value=httpx.Response(400, json={"error": {
        "message": "private generated arguments",
        "failed_generation": {"attempted_arguments": "private prompt content"},
    }}))
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    with TestClient(app) as client:
        response = client.post("/api/chat", json={
            "provider": "groq", "messages": [{"role": "user", "content": "hello"}],
        })
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "GROQ_TOOL_CALL_INVALID"
        record = client.get("/api/llm/records").json()[0]
        assert record["providerStatus"] == 400
        assert record["providerErrorType"] == "tool_use_failed"
        assert "private" not in response.text + settings.llm_record_path.read_text()

        transport.return_value = httpx.Response(400, json={"error": {
            "message": "private invalid request",
        }})
        second = client.post("/api/chat", json={
            "provider": "groq", "messages": [{"role": "user", "content": "again"}],
        })
        assert second.json()["error"]["code"] == "GROQ_BAD_REQUEST"


def test_tool_call_format_retry_is_counted(settings, monkeypatch):
    bad = httpx.Response(400, json={"error": {"code": "tool_use_failed", "failed_generation": "bad"}})
    transport = AsyncMock(side_effect=[bad, reply("Done")])
    monkeypatch.setattr(httpx.AsyncClient, "post", transport)
    app = create_app(replace(settings, groq_api_key="fixture"))
    result = app.state.llm
    import asyncio
    from ai_coder.config import Provider
    response = asyncio.run(result.complete(
        [{"role": "user", "content": "Do it"}],
        system_instruction="Test", provider=Provider.GROQ,
        tools=[{"name": "listFiles", "description": "List files", "parameters": {"type": "object", "properties": {}}}],
    ))
    assert response["usage"]["apiCalls"] == 2
    assert transport.await_count == 2
    assert transport.await_args_list[0].kwargs["json"]["temperature"] == 0.2
    assert transport.await_args_list[1].kwargs["json"]["temperature"] == 0.1
    completed = json.loads(settings.llm_record_path.read_text().splitlines()[-1])
    assert completed["apiCalls"] == 2
