# Author: Ching Kao
# Student ID: 85768427
"""Exercise the real gateway, agent graph and MCP through Groq's HTTP contract."""
import json
import io
from dataclasses import replace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient

from ai_coder.main import create_app


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


def test_workspace_chat_runs_red_green_via_groq(settings, monkeypatch):
    source = "const test = require('node:test');\nconst assert = require('node:assert/strict');\ntest('adds', () => assert.equal(require('./add.cjs').add(1,2), 3));"
    transport = AsyncMock(side_effect=[
        reply(tool="startRun", arguments={"description": "Build an adder", "requirements": []}),
        reply(json.dumps({"spec": "Export add.", "features": [{"title": "Addition", "criteria": ["add(1,2) returns 3"]}]})),
        reply(tool="writeFile", arguments={"path": "add.test.js", "content": source}),
        reply(json.dumps({"decision": "expected_failure", "reason": "The add module is missing."})),
        reply(tool="writeFile", arguments={"path": "add.cjs", "content": "exports.add = (a,b) => a+b;"}),
        reply(tool="writeFile", arguments={"path": "index.html", "content": "<title>Addition</title>"}),
        httpx.Response(429, json={"error": {"message": "quota"}}),
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
    records = [json.loads(row) for row in settings.llm_record_path.read_text().splitlines()]
    completed = [record for record in records if record["event"] == "completed"]
    assert len(completed) == transport.await_count - 1
    assert any(record["event"] == "failed" and record.get("errorCode") == "GROQ_RATE_LIMIT" for record in records)
    assert all(record["provider"] == "groq" and record["resolvedModel"] == "resolved-groq-model" for record in completed)
    assert {r.get("role") for r in completed} == {None, "coordinator", "planner", "tester", "coder"}


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
