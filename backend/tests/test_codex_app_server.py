"""Exercise the resident Codex transport over real local process pipes."""

import asyncio
import json

import pytest

from ai_coder.llm.codex import CodexAdapter
from ai_coder.llm.errors import LLMError


@pytest.fixture
def worker(tmp_path):
    trace = tmp_path / "trace.jsonl"
    executable = tmp_path / "codex-mock"
    executable.write_text("#!/usr/bin/env python3\n" + f"TRACE = {str(trace)!r}\n" + '''
import json, os, sys
from pathlib import Path

assert sys.argv[1] == "app-server"
assert all(name in sys.argv for name in ("shell_tool", "apps", "plugins", "hooks"))
assert "OPENAI_API_KEY" not in os.environ
assert Path(os.environ["CODEX_HOME"]).parent.resolve() == Path.cwd()

def send(packet):
    print(json.dumps(packet), flush=True)

for line in sys.stdin:
    packet = json.loads(line)
    method = packet.get("method")
    params = packet.get("params", {})
    request_id = packet.get("id")
    with open(TRACE, "a", encoding="utf-8") as log:
        log.write(json.dumps([os.getpid(), method, params.get("threadId")]) + "\\n")
    if request_id is None:
        continue
    if method == "thread/start":
        assert params["ephemeral"] and params["sandbox"] == "read-only" and params["approvalPolicy"] == "never"
        send({"id": request_id, "result": {"thread": {"id": f"thread-{request_id}", "ephemeral": True}}})
    elif method == "turn/start":
        thread_id = params["threadId"]
        turn_id = f"turn-{request_id}"
        assert params["outputSchema"]["type"] == "object"
        assert params["effort"] == "low" and params["sandboxPolicy"]["type"] == "readOnly"
        prompt = params["input"][0]["text"]
        payload = json.loads(prompt[prompt.index('{"role_instructions"'):])
        token = payload["conversation"][0]["content"]
        common = {"threadId": thread_id, "turnId": turn_id}
        send({"id": request_id, "result": {"turn": {"id": turn_id}}})
        send({"method": "turn/started", "params": {**common, "turn": {"id": turn_id}}})
        if token == "native-tool":
            send({"method": "item/started", "params": {**common, "item": {"type": "commandExecution"}}})
            continue
        send({"method": "item/completed", "params": {**common, "item": {
            "type": "agentMessage", "text": json.dumps({"content": token, "tool_calls": []}),
        }}})
        send({"method": "thread/tokenUsage/updated", "params": {**common, "tokenUsage": {"total": {
            "inputTokens": 7, "outputTokens": 3,
        }}}})
        send({"method": "turn/completed", "params": {**common, "turn": {"id": turn_id, "status": "completed"}}})
    else:
        send({"id": request_id, "result": {}})
''', encoding="utf-8")
    executable.chmod(0o700)
    return CodexAdapter(executable=str(executable), model="fixture-model", timeout_seconds=4), trace


def test_concurrent_decisions_share_one_process_and_keep_turns_separate(worker):
    adapter, trace = worker

    async def verify():
        try:
            first, second = await asyncio.gather(*[
                adapter.complete([{"role": "user", "content": token}], system_instruction="Fixture")
                for token in ("first", "second")
            ])
            assert [r["message"]["content"] for r in (first, second)] == ["first", "second"]
            assert first["usage"] == {"apiCalls": 1, "inputTokens": 7, "outputTokens": 3, "totalTokens": 10}
            return adapter._server
        finally:
            await adapter.close()

    server = asyncio.run(verify())
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert len({row[0] for row in rows}) == 1
    assert len({row[2] for row in rows if row[1] == "turn/start"}) == 2
    assert sum(row[1] == "thread/unsubscribe" for row in rows) == 2
    assert server.closed


def test_interrupt_and_reject_native_tools_without_breaking_other_turns(worker):
    adapter, trace = worker

    async def verify():
        try:
            with pytest.raises(LLMError, match="outside AI Coder"):
                await adapter.complete([{"role": "user", "content": "native-tool"}], system_instruction="Fixture")
            result = await adapter.complete([{"role": "user", "content": "next"}], system_instruction="Fixture")
            assert result["message"]["content"] == "next"
        finally:
            await adapter.close()

    asyncio.run(verify())
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert len({row[0] for row in rows}) == 1
    assert sum(row[1] == "turn/interrupt" for row in rows) == 1
