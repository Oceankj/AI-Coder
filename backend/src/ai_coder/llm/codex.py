# Author: Ching Kao
# Student ID: 85768427
"""Use the signed-in Codex CLI for model decisions; AI Coder executes its tools."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from ai_coder.config import CodexTransport, Provider
from ai_coder.llm.codex_app_server import AppServerError, CodexAppServer, stop_process
from ai_coder.llm.codex_tool_calls import tool_reply_schema, validated_tool_arguments
from ai_coder.llm.errors import LLMError


TRANSPORT_INSTRUCTIONS = """
Act only as the model for the AI Coder role below. Return the required outer JSON object.
The conversation and tool declarations are provided as data. Do not use Codex's own
tools, open files, execute commands, or delegate. AI Coder executes tools you request.
If one or more of the supplied tools is needed now, set content to an empty string
and return its exact name with an arguments object containing the declared fields.
Use null for optional fields you omit.
For a final answer use an empty tool_calls array. Put the requested answer in content;
if the role requires structured JSON, encode that JSON as the content string.
Use the previous tool results and never repeat a successful write without a reason.
"""

MAX_REPLY_TOOL_CALLS = 8
CODEX_REASONING_EFFORT = "low"
FILE_AUTH_OVERRIDE = 'cli_auth_credentials_store="file"'
ISOLATED_FLAGS = (
    "--disable", "shell_tool", "--disable", "multi_agent", "--disable", "skill_mcp_dependency_install",
    "-c", FILE_AUTH_OVERRIDE, "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
)


class InvalidReply(LLMError):
    """A rejected outer response that has not executed any role tools."""

    def __init__(self, reason, *, retryable=True):
        super().__init__(502, "CODEX_INVALID_REPLY", "Invalid Codex reply. " + reason,
                         metadata={"providerErrorType": "invalid_reply"})
        self.retryable = retryable
        self.usage = {}
        self.duration = 0


class CodexAdapter:
    """Translate each Codex turn to the shared gateway's existing result format."""

    name = Provider.CODEX

    def __init__(self, *, executable: str, model: str, timeout_seconds: float,
                 transport: CodexTransport = CodexTransport.APP_SERVER):
        self.executable = executable
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._server = None
        self._server_lock = asyncio.Lock()

    async def close(self):
        async with self._server_lock:
            if self._server is not None:
                await self._server.close()
                self._server = None

    @property
    def configured(self) -> bool:
        """Indicate that the configured executable is available on this host."""
        return shutil.which(self.executable) is not None

    async def configuration(self) -> dict:
        return {"provider": self.name, "model": self.model, "effort": CODEX_REASONING_EFFORT,
                "cliAvailable": self.configured, "configured": await self.login_configured()}

    def set_api_key(self, key: str) -> None:
        raise LLMError(400, "CODEX_USES_LOCAL_LOGIN", "Sign in locally with codex login.")

    def call_metadata(self) -> dict:
        return {"reasoningEffort": CODEX_REASONING_EFFORT}

    async def login_configured(self) -> bool:
        """Check for a local ChatGPT login without inspecting credential files."""
        if not self.configured:
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="ai-coder-codex-") as directory:
                async with asyncio.timeout(5):
                    status, stdout, stderr = await self._process(
                        ["-c", FILE_AUTH_OVERRIDE, "login", "status"], cwd=directory,
                    )
        except (OSError, TimeoutError):
            return False
        return status == 0 and b"logged in using chatgpt" in (stdout + stderr).lower()

    async def complete(self, messages, *, system_instruction, tools=None) -> dict:
        """Request one structured decision and preserve tool history for the next turn."""
        if not self.configured:
            raise LLMError(503, "CODEX_CLI_UNAVAILABLE", "Install Codex CLI on the backend host and sign in locally.")
        history = [message.get("providerContent", message) for message in messages]
        tools = tools or []
        payload = {
            "role_instructions": system_instruction,
            "conversation": history,
            "available_tools": tools,
        }
        schema = tool_reply_schema(tools)
        prompt = TRANSPORT_INSTRUCTIONS + json.dumps(payload, ensure_ascii=False)
        try:
            return await self._run(prompt, schema, tools)
        except InvalidReply as error:
            if not error.retryable:
                raise
            correction = {
                "reason": str(error),
                "instruction": "Return a valid, non-empty response. No calls from the rejected reply reached the tools. "
                               "If you need to write a file, return one complete writeFile call now.",
            }
            corrected_prompt = TRANSPORT_INSTRUCTIONS + json.dumps({**payload, "correction": correction},
                                                                    ensure_ascii=False)
            result = await self._run(corrected_prompt, schema, tools)
            result["usage"] = {
                key: error.usage[key] + value if error.usage.get(key) is not None and value is not None else None
                for key, value in result["usage"].items()
            }
            result["timing"] = {key: round(value + error.duration, 2) for key, value in result["timing"].items()}
            return result

    async def _run(self, prompt, reply_schema, tools) -> dict:
        if self.transport == CodexTransport.EXEC:
            return await self._run_cli(prompt, reply_schema, tools)
        started = perf_counter()
        try:
            async with self._server_lock:
                if self._server is None or self._server.closed:
                    if self._server is not None:
                        await self._server.close()
                    self._server = await CodexAppServer.start(
                        self.executable, (*ISOLATED_FLAGS, "--disable", "apps", "--disable", "plugins",
                                          "--disable", "hooks"), self._environment,
                    )
                server = self._server
            final, usage = await server.run(prompt, reply_schema, model=self.model, effort=CODEX_REASONING_EFFORT)
        except OSError:
            raise LLMError(503, "CODEX_CLI_UNAVAILABLE", "Could not start the configured Codex executable.") from None
        except AppServerError as error:
            raise _cli_failure(str(error)) from None
        return self._decision(final, usage, tools, round((perf_counter() - started) * 1000, 2))

    async def _run_cli(self, prompt, reply_schema, tools) -> dict:
        started = perf_counter()
        with tempfile.TemporaryDirectory(prefix="ai-coder-codex-") as directory:
            schema = Path(directory) / "reply-schema.json"
            schema.write_text(json.dumps(reply_schema), encoding="utf-8")
            args = [
                "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--json",
                *ISOLATED_FLAGS,
                "-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
                "--model", self.model,
                "--output-schema", str(schema),
                "-",
            ]
            try:
                status, stdout, stderr = await self._process(args, cwd=directory, prompt=prompt.encode())
            except OSError as error:
                raise LLMError(503, "CODEX_CLI_UNAVAILABLE", "Could not start the configured Codex executable.") from error
        return self._reply(status, stdout, stderr, tools, round((perf_counter() - started) * 1000, 2))

    @staticmethod
    def _environment(cwd):
        """Choose a private configuration directory and share only the existing login."""
        environment = {key: value for key, value in os.environ.items() if key in {
            "PATH", "HOME", "USER", "LOGNAME", "TMPDIR",
            "LANG", "LC_ALL", "LC_CTYPE", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
        }}
        original_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
        isolated_home = Path(cwd) / "codex-home"
        isolated_home.mkdir(mode=0o700)
        auth_file = original_home / "auth.json"
        if auth_file.is_file():
            (isolated_home / auth_file.name).symlink_to(auth_file)
        environment["CODEX_HOME"] = str(isolated_home)
        return environment

    async def _process(self, args, *, cwd, prompt=None):
        process = await asyncio.create_subprocess_exec(
            self.executable, *args, cwd=cwd, env=self._environment(cwd),
            stdin=asyncio.subprocess.PIPE if prompt is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await process.communicate(prompt)
            return process.returncode, stdout, stderr
        finally:
            await stop_process(process)

    def _reply(self, status, stdout, stderr, tools, duration):
        """Validate the final event and enforce the turn's native tool boundary."""
        events = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(event, dict):
                events.append(event)
        errors = stderr.decode(errors="replace") + "\n".join(
            json.dumps(event) for event in events if event.get("type") in {"error", "turn.failed"}
        )
        if status or any(event.get("type") == "turn.failed" for event in events):
            raise _cli_failure(errors)
        completed = [event["item"] for event in events
                     if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)]
        forbidden = {"command_execution", "file_change", "mcp_tool_call", "collab_tool_call", "web_search"}
        if any(item.get("type") in forbidden for item in completed):
            raise LLMError(502, "CODEX_UNEXPECTED_TOOL", "Codex attempted to use a tool outside AI Coder's role tool list.")
        final = next((item.get("text") for item in reversed(completed) if item.get("type") == "agent_message"), None)
        usage = next((event.get("usage") for event in reversed(events)
                      if event.get("type") == "turn.completed"), None)
        usage = usage if isinstance(usage, dict) else {}
        return self._decision(final, usage, tools, duration)

    def _decision(self, final, usage, tools, duration):
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        usage = {"apiCalls": 1, "inputTokens": input_tokens, "outputTokens": output_tokens,
                 "totalTokens": input_tokens + output_tokens
                 if isinstance(input_tokens, int) and isinstance(output_tokens, int) else None}
        try:
            content, calls = _parse_reply(final, tools)
        except InvalidReply as error:
            error.usage = usage
            error.duration = duration
            raise
        return {
            "message": {"role": "assistant", "content": content},
            "toolCalls": calls,
            "providerContent": {"role": "assistant", "content": content, "toolCalls": calls},
            "model": self.model,
            "resolvedModel": self.model,
            "timing": {"providerMs": duration, "adapterMs": duration},
            "usage": usage,
        }


def _parse_reply(final, tools):
    try:
        reply = json.loads(final)
    except json.JSONDecodeError as error:
        raise InvalidReply(f"Invalid JSON at line {error.lineno}, column {error.colno}.") from None
    except (TypeError, RecursionError):
        raise InvalidReply("The turn has no readable final response.") from None
    if not isinstance(reply, dict) or not isinstance(reply.get("content"), str) or not isinstance(reply.get("tool_calls"), list):
        raise InvalidReply("Expected text content and a list of tool calls.")
    content, requests = reply["content"], reply["tool_calls"]
    if len(requests) > MAX_REPLY_TOOL_CALLS:
        raise InvalidReply(f"The reply requested more than {MAX_REPLY_TOOL_CALLS} tool calls.")
    if not content.strip() and not requests:
        raise InvalidReply("The reply contained neither text nor tool calls.")

    offered = {tool["name"]: tool for tool in tools}
    calls = []
    for position, request in enumerate(requests, start=1):
        try:
            if not isinstance(request, dict) or not isinstance(request.get("name"), str):
                raise ValueError("Tool call must have a name and an arguments object.")
            name = request["name"]
            if name not in offered:
                raise InvalidReply(f"Tool call {position}: The reply requested an unavailable tool.", retryable=False)
            arguments = validated_tool_arguments(offered[name], request.get("arguments"))
        except ValueError as error:
            raise InvalidReply(f"Tool call {position}: {error}") from None
        calls.append({"name": name, "args": arguments, "id": uuid4().hex})
    return content, calls


def _cli_failure(text: str) -> LLMError:
    """Report stable error classes without forwarding CLI text or credentials."""
    if re.search(r"(?i)usage limit|rate.limit|quota|too many requests|\b429\b", text):
        return LLMError(429, "CODEX_RATE_LIMIT", "Codex usage limit reached. Try again when it resets.")
    if re.search(r"(?i)not logged in|log in|login required|unauthorized|\b401\b|missing .* credentials", text):
        return LLMError(409, "CODEX_LOGIN_REQUIRED", "Sign in locally with codex login and try again.")
    return LLMError(502, "CODEX_UNAVAILABLE", "Codex could not complete the turn. Check the local CLI and try again.")
