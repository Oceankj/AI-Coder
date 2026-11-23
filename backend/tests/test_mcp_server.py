# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""Stage 3, step 4: the MCP server.

The server is tested through a real MCP client session (initialize,
tools/list, tools/call) connected in memory. Step 5 tests the same server as
a stdio subprocess.
"""
import asyncio
import json
import shutil

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from ai_coder.mcp.server import ROLE_TOOLS, build_scope, create_mcp_server, parse_args
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage

PLANNER, CODER, TESTER = AgentRole.PLANNER, AgentRole.CODER, AgentRole.TESTER


@pytest.fixture
def storage(tmp_path):
    """A FileStorage rooted in the test's temporary folder."""
    return FileStorage(tmp_path / "workspaces")


@pytest.fixture
def context(storage):
    """A run with one published task for each role."""
    workspace = storage.create_workspace("Test")
    run = storage.create_run(workspace.id, "Music Playlist Mixer", ["Mix songs"])
    context = RunContext(workspace.id, run.id)
    return context


def session_run(storage, context, role, steps):
    """Open an MCP client session to `role`'s server and run `steps(session)`."""
    from ai_coder.mcp.tools.scope import ToolScope

    async def main():
        server = create_mcp_server(ToolScope(storage, context, role))
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await steps(session)

    return asyncio.run(main())


@pytest.mark.parametrize("role", [PLANNER, CODER, TESTER])
def test_each_role_sees_only_its_tools(storage, context, role):
    """tools/list returns the role's tools, each with a description for the LLM."""

    async def steps(session):
        return (await session.list_tools()).tools

    tools = session_run(storage, context, role, steps)

    assert [tool.name for tool in tools] == list(ROLE_TOOLS[role])
    assert all(tool.description for tool in tools)


def test_hidden_tool_cannot_be_called(storage, context):
    """A Planner calling writeFile gets an error, even though the model guessed the name."""

    async def steps(session):
        return await session.call_tool("writeFile", {"path": "a.js", "content": "x"})

    result = session_run(storage, context, PLANNER, steps)

    assert result.isError
    assert not (storage.project_dir(context) / "a.js").exists()


def test_coder_session_end_to_end(storage, context):
    """A Coder can write, read, and list project files through MCP."""

    async def steps(session):
        wrote = await session.call_tool("writeFile", {"path": "playlist.js", "content": "export const add = (a, b) => a + b;\n"})
        read = await session.call_tool("readFile", {"path": "playlist.js"})
        listed = await session.call_tool("listFiles", {})
        return wrote, read, listed

    wrote, read, listed = session_run(storage, context, CODER, steps)

    assert not any(r.isError for r in (wrote, read, listed))
    assert wrote.content[0].text == "Wrote playlist.js (36 bytes)."
    assert read.content[0].text == "export const add = (a, b) => a + b;\n"
    assert listed.structuredContent == {"files": [{"path": "playlist.js", "size": 36}]}
    assert len(listed.content) == 1  # one JSON message, not one per file


def test_empty_project_lists_an_empty_array(storage, context):
    """An empty project gives the model '{"files": []}', not an empty reply."""

    async def steps(session):
        return await session.call_tool("listFiles", {})

    result = session_run(storage, context, CODER, steps)

    assert json.loads(result.content[0].text) == {"files": []}


def test_tool_errors_reach_the_model_as_readable_text(storage, context):
    """A refused call is an MCP error result whose text explains the rule."""
    (storage.project_dir(context) / "playlist.js").write_text("secret")

    async def steps(session):
        return await session.call_tool("readFile", {"path": "playlist.js"})

    result = session_run(storage, context, TESTER, steps)

    assert result.isError
    assert "The tester may not read 'playlist.js'" in result.content[0].text
    assert "secret" not in result.content[0].text


def test_invalid_arguments_are_rejected(storage, context):
    """Arguments are validated against the tool's schema before the tool runs."""

    async def steps(session):
        return await session.call_tool("writeFile", {"path": "a.js", "content": 123})

    result = session_run(storage, context, CODER, steps)

    assert result.isError
    assert not (storage.project_dir(context) / "a.js").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_tester_runs_checks_over_mcp(storage, context):
    """runChecks over MCP returns the structured result and records it."""
    project = storage.project_dir(context)
    (project / "package.json").write_text('{"type": "module"}\n')
    (project / "playlist.js").write_text("export const add = (a, b) => a + b;\n")

    async def steps(session):
        await session.call_tool("writeFile", {"path": "add.test.js", "content": (
            'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
            'import { add } from "./playlist.js";\ntest("adds", () => assert.equal(add(1, 2), 3));\n'
        )})
        return await session.call_tool("runChecks", {})

    result = session_run(storage, context, TESTER, steps)

    assert not result.isError
    assert result.structuredContent["outcome"] == "passed"
    assert result.structuredContent["passed"] == 1
    assert storage.list_check_executions(context)[0].outcome == "passed"


# --- Startup arguments ----------------------------------------------------------


def test_startup_arguments_bind_the_scope(storage, context):
    """The command line fixes the run and role for the whole session."""
    args = parse_args([
        "--workspaces-root", str(storage.root),
        "--workspace-id", context.workspace_id,
        "--run-id", context.run_id,
        "--role", "tester",
    ])
    scope = build_scope(args)
    assert scope.context == context
    assert scope.role is TESTER


def test_unknown_run_stops_the_server(storage, context):
    """A server for a run that does not exist exits instead of serving."""
    args = parse_args([
        "--workspaces-root", str(storage.root),
        "--workspace-id", context.workspace_id,
        "--run-id", "no-such-run",
        "--role", "coder",
    ])
    with pytest.raises(SystemExit, match="does not exist"):
        build_scope(args)


def test_unknown_role_is_refused():
    """Only planner, coder, and tester are valid roles."""
    with pytest.raises(SystemExit):
        parse_args(["--workspaces-root", ".", "--workspace-id", "w", "--run-id", "r", "--role", "admin"])
