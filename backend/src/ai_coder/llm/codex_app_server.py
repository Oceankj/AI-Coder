"""One local Codex process with isolated conversations for gateway decisions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import itertools
import json
import os
from pathlib import Path
import signal
from tempfile import TemporaryDirectory

from ai_coder.llm.errors import LLMError


class AppServerError(RuntimeError):
    """A transport or turn error, sanitized by the Codex adapter."""


async def stop_process(process):
    if process.returncode is None:
        with suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        await process.wait()


class CodexAppServer:
    _TURN_EVENTS = {"turn/started", "turn/completed", "item/started", "item/completed", "thread/tokenUsage/updated"}
    _MODEL_ITEMS = {"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction"}

    def __init__(self, process, directory):
        self.process = process
        self.directory = directory
        self._ids = itertools.count(1)
        self._requests = {}
        self._events = {}
        self._turns = {}
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def start(cls, executable, args, environment):
        directory = TemporaryDirectory(prefix="ai-coder-app-server-")
        server = None
        try:
            process = await asyncio.create_subprocess_exec(
                executable, "app-server", *args, cwd=directory.name, env=environment(Path(directory.name)),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True, limit=4 * 1024 * 1024,
            )
            server = cls(process, directory)
            async with asyncio.timeout(5):
                await server._request("initialize", {"clientInfo": {"name": "ai_coder", "version": "0.1.0"}})
                await server._send({"method": "initialized"})
            return server
        except BaseException:
            if server is not None:
                await server.close()
            else:
                directory.cleanup()
            raise

    @property
    def closed(self):
        return self.process.returncode is not None or self._reader.done()

    async def close(self):
        await stop_process(self.process)
        self._reader.cancel()
        with suppress(asyncio.CancelledError):
            await self._reader
        self.directory.cleanup()

    async def _send(self, message):
        if self.closed:
            raise AppServerError("The Codex app server has stopped.")
        try:
            self.process.stdin.write(json.dumps(message).encode() + b"\n")
            await self.process.stdin.drain()
        except (OSError, RuntimeError) as error:
            raise AppServerError("Could not send a request to Codex.") from error

    async def _request(self, method, params):
        request_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._requests[request_id] = future
        try:
            await self._send({"id": request_id, "method": method, "params": params})
            return await future
        finally:
            self._requests.pop(request_id, None)
            if future.done() and not future.cancelled():
                future.exception()

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                method = message.get("method")
                request_id = message.get("id")
                if request_id is not None and method is not None:
                    await self._send({"id": request_id, "error": {
                        "code": -32601, "message": "AI Coder does not execute server requests.",
                    }})
                elif request_id is not None:
                    future = self._requests.get(request_id)
                    if future is not None and not future.done():
                        if "error" in message:
                            future.set_exception(AppServerError(json.dumps(message["error"])))
                        else:
                            future.set_result(message.get("result"))
                elif method in self._TURN_EVENTS:
                    params = message.get("params", {})
                    thread_id = params.get("threadId")
                    queue = self._events.get(thread_id)
                    if queue is not None:
                        if method == "turn/started":
                            self._turns[thread_id] = params.get("turn", {}).get("id")
                        queue.put_nowait((method, params))
        except (AppServerError, ValueError, OSError, AttributeError, TypeError):
            # Protocol contents can include prompts and credentials. Report only the boundary failure.
            pass
        finally:
            for future in self._requests.values():
                if not future.done():
                    future.set_exception(AppServerError("Codex stopped responding."))
            for queue in self._events.values():
                queue.put_nowait((None, {}))

    async def run(self, prompt, schema, *, model, effort):
        cwd = self.directory.name
        reply = await self._request("thread/start", {
            "model": model, "cwd": cwd, "sandbox": "read-only", "approvalPolicy": "never", "ephemeral": True,
        })
        thread = reply.get("thread", {}) if isinstance(reply, dict) else {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str):
            raise AppServerError("Codex did not create an isolated conversation.")
        queue = asyncio.Queue()
        self._events[thread_id] = queue
        turn_id = None
        completed = False
        try:
            if thread.get("ephemeral") is not True:
                raise AppServerError("Codex did not create an ephemeral conversation.")
            if reply.get("instructionSources"):
                raise AppServerError("Codex loaded instructions outside the AI Coder role.")
            started = await self._request("turn/start", {
                "threadId": thread_id, "input": [{"type": "text", "text": prompt}],
                "effort": effort, "outputSchema": schema, "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"},
            })
            turn_id = started.get("turn", {}).get("id") if isinstance(started, dict) else None
            if not isinstance(turn_id, str):
                raise AppServerError("Codex did not return a turn ID.")
            final, usage = None, {}
            while True:
                method, params = await queue.get()
                if method is None:
                    raise AppServerError("Codex stopped before finishing the turn.")
                if params.get("turnId", turn_id) != turn_id:
                    continue
                if method in {"item/started", "item/completed"}:
                    item = params.get("item", {})
                    kind = item.get("type")
                    if kind not in self._MODEL_ITEMS:
                        raise LLMError(502, "CODEX_UNEXPECTED_TOOL", "Codex used a tool outside AI Coder's role tool list.")
                    if method == "item/completed" and kind == "agentMessage" and item.get("phase") != "commentary":
                        final = item.get("text")
                elif method == "thread/tokenUsage/updated":
                    counts = params.get("tokenUsage", {}).get("total", {})
                    usage = {"input_tokens": counts.get("inputTokens"), "output_tokens": counts.get("outputTokens")}
                elif method == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("id") != turn_id:
                        continue
                    completed = True
                    if turn.get("status") != "completed":
                        raise AppServerError(json.dumps(turn.get("error")))
                    return final, usage
        finally:
            self._events.pop(thread_id, None)
            observed_turn = self._turns.pop(thread_id, None)
            active = turn_id or observed_turn
            if not self.closed:
                with suppress(AppServerError, TimeoutError):
                    async with asyncio.timeout(2):
                        if not completed and active is not None:
                            await self._request("turn/interrupt", {"threadId": thread_id, "turnId": active})
                        await self._request("thread/unsubscribe", {"threadId": thread_id})
