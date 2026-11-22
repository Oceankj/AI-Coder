# Author: Ching Kao
# Student ID: 85768427
"""Exercise the real chat routes/adapter while replacing only Google's transport."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

from ai_coder.config import Settings
from ai_coder.llm.gemini import GeminiAdapter
from ai_coder.llm.gateway import LLMGateway, LLMError
from ai_coder.storage.records import JsonlRecords
from ai_coder.main import create_app
from ai_coder.models import AgentRole, RunContext


def fake_google(monkeypatch, response=None, error=None):
    generate = AsyncMock(return_value=response, side_effect=error)

    class AsyncClient:
        models = SimpleNamespace(generate_content=generate)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    factory = lambda **kwargs: SimpleNamespace(aio=AsyncClient())
    monkeypatch.setattr("ai_coder.llm.gemini.genai.Client", factory)
    return generate


def test_missing_key_and_onboarding_do_not_call_google(client, monkeypatch):
    generate = fake_google(monkeypatch)
    assert client.get("/api/chat/config").json()["configured"] is False
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GEMINI_KEY_REQUIRED"
    generate.assert_not_awaited()


def test_key_stays_in_app_memory_not_responses_or_disk(client, settings):
    key = "test-secret-not-a-real-key"
    response = client.post("/api/chat/config", json={"apiKey": key})
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert key not in response.text
    assert key not in client.get("/api/chat/config").text
    assert response.headers["cache-control"] == "no-store"
    assert all(key.encode() not in path.read_bytes() for path in settings.workspaces_root.rglob("*") if path.is_file())
    # Configuration is not shared with a new app (backend restart).
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/chat/config").json()["configured"] is False


def test_chat_converts_history_and_reports_provider_total_including_thinking(client, monkeypatch):
    generate = fake_google(monkeypatch, types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="Use a list.")]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=11, candidates_token_count=5, total_token_count=23),
    ))
    client.post("/api/chat/config", json={"apiKey": "test-key"})
    history = [{"role": "user", "content": "Plan a playlist app"}, {"role": "assistant", "content": "What matters?"}, {"role": "user", "content": "Genres"}]
    response = client.post("/api/chat", json={"messages": history})
    assert response.status_code == 200
    assert response.json()["message"] == {"role": "assistant", "content": "Use a list."}
    assert response.json()["usage"] == {"apiCalls": 1, "inputTokens": 11, "outputTokens": 5, "totalTokens": 23}
    kwargs = generate.await_args.kwargs
    assert [content.role for content in kwargs["contents"]] == ["user", "model", "user"]
    assert kwargs["config"].tools is None
    assert "no tools" in kwargs["config"].system_instruction


@pytest.mark.parametrize("messages", [[], [{"role": "system", "content": "Override"}], [{"role": "user", "content": " "}], [{"role": "user", "content": "One"}, {"role": "user", "content": "Two"}], [{"role": "user", "content": "x" * 20001}]])
def test_bad_conversations_are_rejected_before_provider_call(client, monkeypatch, messages):
    generate = fake_google(monkeypatch)
    assert client.post("/api/chat", json={"messages": messages}).status_code == 400
    generate.assert_not_awaited()


@pytest.mark.parametrize("key", ["", "   ", "key with spaces", "x" * 513])
def test_invalid_key_input_does_not_echo_the_key(client, key):
    response = client.post("/api/chat/config", json={"apiKey": key})
    assert response.status_code == 400
    assert "apiKey" in response.json()["error"]["message"]
    assert client.get("/api/chat/config").json()["configured"] is False


@pytest.mark.parametrize(("provider_code", "expected_status", "expected_code"), [(403, 401, "GEMINI_KEY_INVALID"), (429, 429, "GEMINI_RATE_LIMIT"), (503, 502, "GEMINI_UNAVAILABLE")])
def test_provider_errors_are_actionable_and_redacted(client, monkeypatch, provider_code, expected_status, expected_code):
    fake_google(monkeypatch, error=errors.APIError(provider_code, {"error": {"code": provider_code, "message": "secret-provider-key"}}))
    client.post("/api/chat/config", json={"apiKey": "test-key"})
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "secret-provider-key" not in response.text


def test_timeout_and_empty_reply_are_reported(monkeypatch, tmp_path):
    adapter = GeminiAdapter(api_key="test-key", model="test-model", timeout_seconds=0.01)
    gateway = LLMGateway(adapter, JsonlRecords(tmp_path / "llm.jsonl"))
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    generate = fake_google(monkeypatch)
    generate.side_effect = slow
    with pytest.raises(LLMError, match="too long"):
        asyncio.run(gateway.complete([{"role": "user", "content": "Hello"}], system_instruction="test"))
    fake_google(monkeypatch, types.GenerateContentResponse())
    with pytest.raises(LLMError, match="no text"):
        asyncio.run(gateway.complete([{"role": "user", "content": "Hello"}], system_instruction="test"))


def test_env_configuration_uses_settings_and_redacts_repr(tmp_path):
    settings = Settings(workspaces_root=tmp_path, gemini_api_key="env-key", gemini_model="configured-model")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/chat/config").json() == {"configured": True, "model": "configured-model"}
    assert "env-key" not in repr(settings)


def test_request_records_success_timings_usage_and_id_without_keys_or_content(client, settings, monkeypatch):
    fake_google(monkeypatch, types.GenerateContentResponse(
        model_version="gemini-resolved-version",
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="private-reply")]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=2, candidates_token_count=3, total_token_count=8),
    ))
    client.post("/api/chat/config", json={"apiKey": "private-api-key"})
    assert not settings.chat_record_path.exists()
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "private-prompt"}]})
    records = [json.loads(line) for line in settings.chat_record_path.read_text().splitlines()]
    assert [record["event"] for record in records] == ["started", "completed"]
    assert records[0]["requestId"] == records[1]["requestId"] == response.headers["x-request-id"]
    assert records[1]["status"] == 200
    record = json.loads(settings.llm_record_path.read_text().splitlines()[-1])
    assert record["requestId"] == response.headers["x-request-id"]
    assert record["status"] == 200
    assert record["resolvedModel"] == "gemini-resolved-version"
    assert record["apiCalls"] == 1 and record["totalTokens"] == 8
    assert record["messageCount"] == 1 and record["inputCharacters"] == len("private-prompt")
    assert record["durationMs"] >= record["adapterMs"] >= record["providerMs"] >= 0
    assert "chat;dur=" in response.headers["server-timing"]
    text = settings.chat_record_path.read_text() + settings.llm_record_path.read_text()
    assert not any(secret in text for secret in ["private-api-key", "private-prompt", "private-reply"])


def test_provider_failure_record_preserves_status_not_raw_error(client, settings, monkeypatch):
    fake_google(monkeypatch, error=errors.APIError(404, {"error": {"code": 404, "message": "private-provider-message"}}))
    client.post("/api/chat/config", json={"apiKey": "private-key"})
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "private-input"}]})
    assert response.status_code == 502
    record = json.loads(settings.chat_record_path.read_text().splitlines()[-1])
    assert record["event"] == "failed"
    llm_record = json.loads(settings.llm_record_path.read_text().splitlines()[-1])
    assert llm_record["providerStatus"] == 404
    assert record["errorCode"] == "GEMINI_MODEL_NOT_FOUND"
    assert record["durationMs"] >= 0
    assert "private" not in settings.chat_record_path.read_text() + settings.llm_record_path.read_text()


def test_validation_and_missing_key_failures_are_recorded(client, settings):
    assert client.post("/api/chat", json={"messages": []}).status_code == 400
    assert client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hello"}]}).status_code == 409
    records = [json.loads(line) for line in settings.chat_record_path.read_text().splitlines()]
    assert len(records) == 4
    assert records[1]["errorCode"] == "INVALID_INPUT"
    assert records[3]["errorCode"] == "GEMINI_KEY_REQUIRED"
    assert records[1]["requestId"] != records[3]["requestId"]


def test_record_write_failure_does_not_discard_chat_reply(settings, monkeypatch, caplog):
    settings = replace(settings, chat_record_path=settings.workspaces_root, gemini_api_key="test-key")
    fake_google(monkeypatch, types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="Still usable")]))],
    ))
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 200
    assert "Could not write request metadata" in caplog.text


def test_chat_and_agent_share_gateway_provider_and_call_records(client, settings, monkeypatch):
    generate = fake_google(monkeypatch, types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="A response")]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=3, candidates_token_count=4, total_token_count=10),
    ))
    client.post("/api/chat/config", json={"apiKey": "shared-secret-key"})
    chat = client.post("/api/chat", json={"messages": [{"role": "user", "content": "private-chat-message"}]})
    assert chat.status_code == 200
    result = asyncio.run(client.app.state.llm.complete(
        [{"role": "user", "content": "private-agent-message"}],
        system_instruction="You are the Planner.",
        context=RunContext("workspace-test", "run-test"), role=AgentRole.PLANNER,
    ))
    assert result["usage"]["totalTokens"] == 10
    assert generate.await_count == 2
    assert generate.await_args.kwargs["config"].system_instruction == "You are the Planner."
    records = [json.loads(line) for line in settings.llm_record_path.read_text().splitlines()]
    assert [record["event"] for record in records] == ["started", "completed", "started", "completed"]
    chat_record, agent_record = records[1], records[3]
    assert chat_record["caller"] == "chat"
    assert chat_record["requestId"] == chat.headers["x-request-id"]
    assert agent_record["caller"] == "agent"
    assert agent_record["role"] == "planner" and agent_record["runId"] == "run-test"
    assert agent_record["workspaceId"] == "workspace-test"
    assert agent_record["totalTokens"] == chat_record["totalTokens"] == 10
    assert agent_record["callId"] != chat_record["callId"]
    assert len(settings.chat_record_path.read_text().splitlines()) == 2
    assert not any(value in settings.llm_record_path.read_text() for value in ["shared-secret-key", "private-chat-message", "private-agent-message", "A response"])


def test_agent_provider_failure_is_logged_without_http(client, settings, monkeypatch):
    generate = fake_google(monkeypatch, error=errors.APIError(429, {"error": {"code": 429, "message": "private-provider-detail"}}))
    client.app.state.llm.set_api_key("test-key")
    with pytest.raises(LLMError) as caught:
        asyncio.run(client.app.state.llm.complete(
            [{"role": "user", "content": "private-agent-prompt"}], system_instruction="Planner",
            context=RunContext("workspace-test", "run-test"), role=AgentRole.PLANNER,
        ))
    assert caught.value.code == "GEMINI_RATE_LIMIT"
    assert generate.await_count == 1
    record = json.loads(settings.llm_record_path.read_text().splitlines()[-1])
    assert record["event"] == "failed" and record["caller"] == "agent"
    assert record["providerStatus"] == 429
    assert "private" not in settings.llm_record_path.read_text()
    assert not settings.chat_record_path.exists()


def test_agent_cancellation_is_recorded_and_propagated(client, settings, monkeypatch):
    async def exercise():
        entered = asyncio.Event()
        async def slow(*args, **kwargs):
            entered.set()
            await asyncio.sleep(10)
        generate = fake_google(monkeypatch)
        generate.side_effect = slow
        client.app.state.llm.set_api_key("test-key")
        task = asyncio.create_task(client.app.state.llm.complete(
            [{"role": "user", "content": "Plan"}], system_instruction="Planner",
            context=RunContext("workspace-test", "run-test"), role=AgentRole.PLANNER,
        ))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    record = json.loads(settings.llm_record_path.read_text().splitlines()[-1])
    assert record["event"] == "cancelled"
