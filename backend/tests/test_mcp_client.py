# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""Stage 3, step 5: the MCP client against a real server subprocess.

Each test starts `python -m ai_coder.mcp.server` over stdio, exactly as an
agent will in stage 4, so these tests cover the whole MCP path.
"""
import asyncio
import shutil
import subprocess
import sys
import time

import pytest

from ai_coder.mcp.client import AgentMCPClient, MCPServerError
from ai_coder.mcp.server import ROLE_TOOLS
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage

PLANNER, CODER, TESTER = AgentRole.PLANNER, AgentRole.CODER, AgentRole.TESTER


@pytest.fixture
def storage(tmp_path):
    """A FileStorage rooted in the test's temporary folder."""
    return FileStorage(tmp_path / "workspaces")


@pytest.fixture
def context(storage):
    """A run with a published Coder and Tester task."""
    workspace = storage.create_workspace("Test")
    run = storage.create_run(workspace.id, "Music Playlist Mixer", ["Mix songs"])
    context = RunContext(workspace.id, run.id)
    return context


def test_coder_works_through_a_real_stdio_server(storage, context):
    """Start the server, list tools, call them, and stop it."""

    async def main():
        async with AgentMCPClient(storage.root, context, CODER) as client:
            tools = await client.list_tools()
            wrote = await client.call_tool("writeFile", {"path": "playlist.js", "content": "export const x = 1;\n"})
            return tools, wrote

    tools, wrote = asyncio.run(main())

    assert [tool.name for tool in tools] == list(ROLE_TOOLS[CODER])
    assert all(tool.description and tool.input_schema["type"] == "object" for tool in tools)
    assert wrote == wrote.__class__(text="Wrote playlist.js (20 bytes).", is_error=False,
                                    structured={"result": "Wrote playlist.js (20 bytes)."})
    assert (storage.project_dir(context) / "playlist.js").read_text() == "export const x = 1;\n"


def test_refused_call_is_a_result_not_an_exception(storage, context):
    """The agent gets the error text to pass back to the LLM."""
    (storage.project_dir(context) / "playlist.js").write_text("secret")

    async def main():
        async with AgentMCPClient(storage.root, context, TESTER) as client:
            return await client.call_tool("readFile", {"path": "playlist.js"})

    result = asyncio.run(main())

    assert result.is_error
    assert "The Tester may read only test files" in result.text
    assert "secret" not in result.text


def test_server_that_cannot_start_raises_a_readable_error(storage, context):
    """A wrong run ID stops the server; the client reports the server's reason."""
    wrong = RunContext(context.workspace_id, "no-such-run")

    async def main():
        async with AgentMCPClient(storage.root, wrong, CODER):
            pass

    with pytest.raises(MCPServerError, match="coder MCP server did not start.*does not exist"):
        asyncio.run(main())


def test_client_used_outside_async_with(storage, context):
    """Calling a tool before the server is started fails clearly."""
    client = AgentMCPClient(storage.root, context, CODER)
    with pytest.raises(MCPServerError, match="not open"):
        asyncio.run(client.call_tool("listFiles"))


@pytest.mark.skipif(shutil.which("node") is None or sys.platform == "win32",
                    reason="needs Node.js and the Unix ps command")
def test_cancelled_agent_leaves_no_processes_behind(storage, context):
    """When the agent's time limit cancels it mid-runChecks, server and node both stop.

    This is what happens when the orchestrator's per-agent time limit passes.
    """
    project = storage.project_dir(context)
    (project / "loop.test.js").write_text('import { test } from "node:test";\ntest("forever", () => { while (true) {} });\n')

    async def agent():
        async with AgentMCPClient(storage.root, context, TESTER, check_timeout_seconds=120) as client:
            await client.call_tool("runChecks")

    marker = str(project.resolve())  # node's command line contains the project path

    async def main():
        task = asyncio.create_task(agent())
        # Make sure node is really running the endless test before cancelling.
        assert await asyncio.to_thread(_wait_for_process, marker, True), "node never started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())

    assert _wait_for_process(marker, running=False), "node or the server is still running"
    assert storage.list_check_executions(context) == []  # an interrupted check records nothing


def _wait_for_process(text: str, running: bool, seconds: float = 10.0) -> bool:
    """Poll `ps` until a process whose command line contains `text` is running (or gone)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        commands = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
        if (text in commands) == running:
            return True
        time.sleep(0.2)
    return False
