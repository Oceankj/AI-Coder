# Author: Ching Kao
# Student ID: 85768427
"""Provider configuration and local failures pass through the shared boundary."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_coder.config import Provider
from ai_coder.llm.codex import CodexAdapter
from ai_coder.llm.gateway import LLMGateway
from ai_coder.storage.records import JsonlRecords


def test_gateway_uses_adapter_interface_without_provider_configuration_details(tmp_path):
    config = {"provider": Provider.CODEX, "configured": False, "cliAvailable": True, "model": "fixture"}
    adapter = SimpleNamespace(configuration=AsyncMock(return_value=config))
    gateway = LLMGateway({Provider.CODEX: adapter}, JsonlRecords(tmp_path / "calls.jsonl"))
    assert asyncio.run(gateway.configuration(Provider.CODEX)) == config
    adapter.configuration.assert_awaited_once_with()


@pytest.mark.parametrize("provider,status,code", [
    (Provider.GEMINI, 409, "GEMINI_KEY_REQUIRED"),
    (Provider.GROQ, 409, "GROQ_KEY_REQUIRED"),
    (Provider.CODEX, 503, "CODEX_CLI_UNAVAILABLE"),
])
def test_local_prerequisite_failures_keep_http_and_gateway_records(client, settings, monkeypatch, provider, status, code):
    monkeypatch.setattr("ai_coder.llm.codex.shutil.which", lambda _: None)
    response = client.post("/api/chat", json={
        "provider": provider, "messages": [{"role": "user", "content": "private input"}],
    })
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    text = settings.llm_record_path.read_text()
    records = [json.loads(line) for line in text.splitlines()]
    assert [record["event"] for record in records] == ["started", "failed"]
    assert records[0]["callId"] == records[1]["callId"]
    assert all(record["requestId"] == response.headers["x-request-id"] for record in records)
    assert records[-1]["provider"] == provider and records[-1]["errorCode"] == code
    assert "private input" not in text


@pytest.mark.parametrize("available,logged_in", [(False, False), (True, False), (True, True)])
def test_codex_configuration_distinguishes_cli_from_local_login(client, monkeypatch, available, logged_in):
    monkeypatch.setattr("ai_coder.llm.codex.shutil.which", lambda _: "/fixture/codex" if available else None)
    process = AsyncMock(return_value=(0 if logged_in else 1, b"Logged in using ChatGPT" if logged_in else b"", b""))
    monkeypatch.setattr(CodexAdapter, "_process", process)
    response = client.get("/api/chat/config?provider=codex")
    assert response.status_code == 200
    assert response.json()["cliAvailable"] is available
    assert response.json()["configured"] is logged_in
    if available:
        assert "login" in process.await_args.args[0]
    else:
        process.assert_not_awaited()
