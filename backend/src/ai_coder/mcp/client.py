# Author: Shih-Yun Huang
# Student ID: 20645816
"""MCP client for the agents: start a role's server, list tools, call tools.

Usage in an agent (stage 4):

    async with AgentMCPClient(settings.workspaces_root, context, AgentRole.CODER) as mcp:
        tools = await mcp.list_tools()        # give these to the LLM
        result = await mcp.call_tool("writeFile", {"path": "index.html", "content": "..."})
        if result.is_error: ...               # send result.text back to the LLM either way

What happens underneath:

1. Entering `async with` starts `python -m ai_coder.mcp.server ...` as a
   subprocess, bound to this run and role, and performs the MCP handshake
   (initialize) over its stdin/stdout.
2. `list_tools` and `call_tool` send JSON-RPC requests over that pipe.
3. Leaving `async with` (normally, on an error, or when the agent is
   cancelled by its time limit) closes the pipe and stops the server and
   anything it started, such as a running `node --test`.

Open and close the client in the same asyncio task (use `async with`): the
SDK's stdio transport requires it.

A tool that refuses a call (bad path, permission, failing validation) is not
an exception here: it comes back as a `ToolResult` with `is_error=True` and a
readable message, which the agent should pass to the LLM so it can correct
itself. Exceptions are raised only when the server itself cannot be reached.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from ai_coder.config import Settings
from ai_coder.mcp.tools.execution import DEFAULT_TIMEOUT_SECONDS
from ai_coder.models import AgentRole, RunContext

# The folder that contains the ai_coder package, so the server subprocess can
# import it even when the backend runs from source without being installed.
_SOURCE_ROOT = Path(__file__).resolve().parents[2]

START_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ToolSpec:
    """One tool as the server describes it; convert this into the LLM's tool format."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema of the arguments


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call."""

    text: str  # what to show the LLM (the result, or the error message)
    is_error: bool  # True when the tool refused or failed
    structured: dict[str, Any] | None = None  # machine-readable form, when the tool has one


class MCPServerError(RuntimeError):
    """The MCP server could not be started or stopped responding."""


class AgentMCPClient:
    """A connection to one MCP server process, bound to one run and role."""

    def __init__(
        self,
        workspaces_root: Path,
        context: RunContext,
        role: AgentRole,
        *,
        max_features: int = Settings.max_features,
        check_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Describe the server to start; nothing runs until `async with`."""
        self.role = role
        self._server = StdioServerParameters(
            command=sys.executable,  # the same Python (and virtual environment) as the backend
            args=[
                "-m", "ai_coder.mcp.server",
                "--workspaces-root", str(Path(workspaces_root).resolve()),
                "--workspace-id", context.workspace_id,
                "--run-id", context.run_id,
                "--role", role.value,
                "--max-features", str(max_features),
                "--check-timeout", str(check_timeout_seconds),
            ],
            # Only harmless variables (PATH, HOME, ...) are passed on, so
            # secrets such as GEMINI_API_KEY never reach the server.
            env={**get_default_environment(), "PYTHONPATH": str(_SOURCE_ROOT)},
        )
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._stderr = None

    async def __aenter__(self) -> AgentMCPClient:
        """Start the server subprocess and complete the MCP handshake."""
        stack = AsyncExitStack()
        try:
            # The server's error output is kept so a failed start can say why.
            self._stderr = stack.enter_context(tempfile.TemporaryFile(mode="w+", encoding="utf-8"))
            read, write = await stack.enter_async_context(stdio_client(self._server, errlog=self._stderr))
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), START_TIMEOUT_SECONDS)
        except BaseException as error:
            message = self._server_errors()
            await stack.aclose()
            if isinstance(error, Exception):
                raise MCPServerError(
                    f"The {self.role.value} MCP server did not start. {message}".strip()
                ) from error
            raise  # cancellation: just clean up
        self._stack, self._session = stack, session
        return self

    async def __aexit__(self, *exc_info) -> None:
        """Stop the server subprocess and everything it started."""
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            await stack.aclose()

    async def list_tools(self) -> list[ToolSpec]:
        """Return the tools this role's server offers (tools/list)."""
        result = await self._require_session().list_tools()
        return [
            ToolSpec(name=tool.name, description=tool.description or "", input_schema=tool.inputSchema)
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Call one tool (tools/call) and return its text, error flag, and structured result."""
        result = await self._require_session().call_tool(name, arguments or {})
        text = "\n".join(part.text for part in result.content if getattr(part, "text", None) is not None)
        return ToolResult(text=text, is_error=bool(result.isError), structured=result.structuredContent)

    def _require_session(self) -> ClientSession:
        """The open session, or a clear error if the client is used outside `async with`."""
        if self._session is None:
            raise MCPServerError("The MCP client is not open; use it inside 'async with'.")
        return self._session

    def _server_errors(self) -> str:
        """What the server printed to stderr (for example why it exited at startup)."""
        if self._stderr is None:
            return ""
        try:
            self._stderr.seek(0)
            return self._stderr.read().strip()[-2000:]
        except (OSError, ValueError):
            return ""
