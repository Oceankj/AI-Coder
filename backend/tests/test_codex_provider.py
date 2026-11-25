# Author: Ching Kao
# Student ID: 85768427
"""Check the Codex structured reply and its role tool boundary."""

import asyncio
import json
from pathlib import Path
from stat import S_IMODE

import pytest
from jsonschema import Draft202012Validator

from ai_coder.config import CodexTransport, Settings
from ai_coder.llm.codex import CodexAdapter
from ai_coder.llm.errors import LLMError
from ai_coder.main import create_app
from fastapi.testclient import TestClient


WRITE_FILE = {
    "name": "writeFile",
    "description": "Write the complete project file.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
READ_FILE = {
    "name": "readFile",
    "description": "Read a project file.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}
RESUME_RUN = {
    "name": "resumeRun",
    "description": "Resume the selected run.",
    "parameters": {
        "type": "object",
        "properties": {
            "clarification": {"type": "string"},
            "run_id": {"type": "string", "default": ""},
        },
        "required": ["clarification"],
    },
}


def event_stream(reply, *, extra=None, input_tokens=100, output_tokens=10):
    """Serialize the CLI events needed to reconstruct one completed turn."""
    events = [
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(reply)}},
        {"type": "turn.completed", "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}},
    ]
    if extra:
        events.insert(1, extra)
    return "\n".join(json.dumps(event) for event in events).encode()


def write_request(path, content):
    return {"name": "writeFile", "arguments": {"path": path, "content": content}}


def tool_reply(*calls):
    return {"content": "", "tool_calls": list(calls)}


def script_process(adapter, monkeypatch, *streams):
    """Exercise the adapter and capture the actual structured-output schema and input."""
    turns = []

    async def process(args, *, cwd, prompt):
        assert len(turns) < len(streams), "Codex CLI was invoked more often than expected"
        schema_file = Path(args[args.index("--output-schema") + 1])
        prompt_text = prompt.decode()
        body = json.loads(prompt_text[prompt_text.index('{"role_instructions"'):])
        turns.append((json.loads(schema_file.read_text()), body))
        return 0, streams[len(turns) - 1], b""

    monkeypatch.setattr(adapter, "_process", process)
    return turns


def complete(adapter, tools):
    return asyncio.run(adapter.complete(
        [{"role": "user", "content": "Implement the current task."}],
        system_instruction="Use only the role's tools.",
        tools=tools,
    ))


@pytest.mark.parametrize("configured_home", [False, True])
def test_codex_subprocesses_load_auth_without_personal_instructions(monkeypatch, tmp_path, configured_home):
    """Login and model subprocesses discover instructions in their private home only."""
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    if configured_home:
        personal = tmp_path / "custom-codex-home"
        monkeypatch.setenv("CODEX_HOME", str(personal))
    else:
        personal = user_home / ".codex"
        monkeypatch.delenv("CODEX_HOME", raising=False)
    personal.mkdir()
    private_files = {
        "auth.json": '{"fixture": "not a credential"}\n',
        "AGENTS.md": "Personal instructions fixture.\n",
        "AGENTS.override.md": "Personal override fixture.\n",
        "config.toml": "# Personal settings fixture.\n",
    }
    for name, content in private_files.items():
        (personal / name).write_text(content, encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-backend-fixture")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "unused-access-token-fixture")
    monkeypatch.setattr("ai_coder.llm.codex.shutil.which", lambda _: "/usr/bin/codex")

    invocations = []

    class Child:
        returncode = 0

        def __init__(self, output):
            self.output = output

        async def communicate(self, input_bytes):
            return self.output, b""

    async def spawn(executable, *args, cwd, env, **kwargs):
        assert executable == "codex"
        working = Path(cwd)
        isolated = Path(env["CODEX_HOME"])
        assert isolated.parent == working
        assert isolated != personal and isolated.is_dir()
        assert not S_IMODE(isolated.stat().st_mode) & 0o077
        assert {entry.name for entry in isolated.iterdir()} == {"auth.json"}
        linked_auth = isolated / "auth.json"
        assert linked_auth.is_symlink()
        assert linked_auth.resolve() == (personal / "auth.json").resolve()
        assert "OPENAI_API_KEY" not in env and "CODEX_ACCESS_TOKEN" not in env
        assert 'cli_auth_credentials_store="file"' in args
        invocations.append((args, working, isolated))
        if "login" in args:
            assert "status" in args
            return Child(b"Logged in using ChatGPT\n")
        assert "exec" in args and "project_doc_max_bytes=0" in args
        assert "--ignore-user-config" in args
        assert args[args.index("--model") + 1] == "gpt-5.6-luna"
        assert 'model_reasoning_effort="low"' in args
        return Child(event_stream({"content": "task response", "tool_calls": []}))

    monkeypatch.setattr("ai_coder.llm.codex.asyncio.create_subprocess_exec", spawn)
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)

    assert asyncio.run(adapter.login_configured())
    result = complete(adapter, [])
    assert result["message"]["content"] == "task response"
    assert len(invocations) == 2
    assert len({working for _, working, _ in invocations}) == 2
    assert all(not working.exists() and not isolated.exists() for _, working, isolated in invocations)
    assert {entry.name: entry.read_text(encoding="utf-8") for entry in personal.iterdir()} == private_files


def test_codex_translates_role_tool_calls_and_usage(monkeypatch):
    """Quoted, multiline source is forwarded without a second layer of JSON parsing."""
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    source = 'const selected = document.querySelector(\'input[name="mood"]:checked\');\nexport { selected };\n'
    write = write_request("playlist.js", source)
    reply = tool_reply(write)
    turns = script_process(adapter, monkeypatch, event_stream(reply))
    result = complete(adapter, [WRITE_FILE])
    assert result["toolCalls"][0]["args"] == {"path": "playlist.js", "content": source}
    assert result["providerContent"]["toolCalls"] == result["toolCalls"]
    assert result["usage"] == {"apiCalls": 1, "inputTokens": 100, "outputTokens": 10, "totalTokens": 110}
    assert len(turns) == 1
    schema, _ = turns[0]
    validator = Draft202012Validator(schema)
    assert validator.is_valid(reply)
    assert not validator.is_valid(tool_reply({"name": "readFile", "arguments": {"path": "playlist.js"}}))
    assert not validator.is_valid(tool_reply({"name": "writeFile", "arguments": {"path": "playlist.js"}}))


def test_codex_corrects_an_empty_reply_once_and_accounts_for_both_calls(monkeypatch):
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    turns = script_process(
        adapter, monkeypatch, event_stream({"content": "", "tool_calls": []}),
        event_stream(tool_reply(write_request("library.test.js", "export {};"))),
    )
    result = complete(adapter, [WRITE_FILE])
    assert len(turns) == 2
    assert "neither text nor tool calls" in turns[1][1]["correction"]["reason"]
    assert result["toolCalls"][0]["args"]["path"] == "library.test.js"
    assert result["usage"] == {"apiCalls": 2, "inputTokens": 200, "outputTokens": 20, "totalTokens": 220}


def test_codex_stops_after_a_repeated_empty_reply(monkeypatch):
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    empty = event_stream({"content": "", "tool_calls": []})
    turns = script_process(adapter, monkeypatch, empty, empty)
    with pytest.raises(LLMError, match="neither text nor tool calls"):
        complete(adapter, [WRITE_FILE])
    assert len(turns) == 2


def test_codex_rejects_a_tool_not_offered_by_role(monkeypatch):
    """A policy violation never becomes an AI Coder tool request."""
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    forbidden = tool_reply(write_request("playlist.js", "export {};\n"))
    turns = script_process(adapter, monkeypatch, event_stream(forbidden))
    with pytest.raises(LLMError, match="unavailable tool") as stopped:
        complete(adapter, [READ_FILE])
    assert stopped.value.code == "CODEX_INVALID_REPLY"
    assert "writeFile" not in str(stopped.value)
    assert not Draft202012Validator(turns[0][0]).is_valid(forbidden)
    assert len(turns) <= 2


def test_codex_preserves_coordinator_defaults_for_null_optional_arguments(monkeypatch):
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    reply = tool_reply({
        "name": "resumeRun",
        "arguments": {"clarification": "Continue writing the remaining files.", "run_id": None},
    })
    turns = script_process(adapter, monkeypatch, event_stream(reply))

    result = complete(adapter, [RESUME_RUN])

    assert len(turns) == 1
    assert Draft202012Validator(turns[0][0]).is_valid(reply)
    args = result["toolCalls"][0]["args"]
    assert args["clarification"] == "Continue writing the remaining files."
    assert args.get("run_id", "") == ""


@pytest.mark.parametrize("tool", ["command_execution", "web_search"])
def test_codex_rejects_internal_tool_use(tool):
    """Only AI Coder executes tools during a role's turn."""
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    event = {"type": "item.completed", "item": {"type": tool}}
    with pytest.raises(LLMError, match="outside AI Coder"):
        adapter._reply(0, event_stream({"content": "done", "tool_calls": []}, extra=event), b"", [], 12)


def test_codex_maps_the_account_limit_without_raw_output():
    """Map the CLI message to a resumable provider failure."""
    adapter = CodexAdapter(executable="codex", model="gpt-5.6-luna", timeout_seconds=10, transport=CodexTransport.EXEC)
    with pytest.raises(LLMError) as error:
        adapter._reply(1, b"", b"usage limit reached; internal diagnostic", [], 12)
    assert error.value.code == "CODEX_RATE_LIMIT"
    assert "internal diagnostic" not in str(error.value)


def test_codex_chat_configuration_and_shared_gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(CodexAdapter, "configured", property(lambda _: True))

    async def login_configured(self):
        return True

    async def run(self, prompt, schema, tools):
        assert "You are the AI Coder Coordinator" in prompt
        assert "Current request" in prompt
        return self._reply(0, event_stream({"content": "hello from Luna", "tool_calls": []}), b"", tools, 12)

    monkeypatch.setattr(CodexAdapter, "login_configured", login_configured)
    monkeypatch.setattr(CodexAdapter, "_run", run)
    settings = Settings(workspaces_root=tmp_path / "workspaces", chat_record_path=tmp_path / "chat.jsonl",
                        llm_record_path=tmp_path / "llm.jsonl")
    with TestClient(create_app(settings)) as client:
        config = client.get("/api/chat/config?provider=codex")
        assert config.json() == {
            "provider": "codex", "configured": True, "model": "gpt-5.6-luna", "effort": "low",
        }

        unwanted_key = client.post("/api/chat/config", json={"provider": "codex", "apiKey": "test-key"})
        assert unwanted_key.status_code == 400
        request = client.post("/api/chat", json={
            "provider": "codex", "messages": [{"role": "user", "content": "Current request"}],
        })
        assert request.status_code == 200
        assert request.json()["message"]["content"] == "hello from Luna"

    rows = [json.loads(line) for line in settings.llm_record_path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["started", "completed"]
    assert all(row["provider"] == "codex" and row["reasoningEffort"] == "low" for row in rows)
    assert rows[-1]["totalTokens"] == 110
