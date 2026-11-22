# Author: Shih-Yun Huang
# Student ID: 20645816
"""The AI Coder MCP server: one process per agent session, over stdio.

The agent's MCP client (step 5) starts this module as a subprocess:

    python -m ai_coder.mcp.server --workspaces-root <dir> \
        --workspace-id <id> --run-id <id> --role coder

The workspace, run, and role come only from these startup arguments and are
fixed for the life of the process (a `ToolScope`). The tools themselves live in
mcp/tools/; this module only exposes them over MCP.

Each role sees only the tools it may use:

| Tool         | Planner | Coder | Tester |
| ------------ | ------- | ----- | ------ |
| listFiles    | yes     | yes   | yes    |
| readFile     | yes     | yes   | yes    |
| writeFile    |         | yes   | yes    |
| runChecks    |         |       | yes    |

Hiding tools a role cannot use keeps the model from trying them, and saves
tokens: the agent sends every tool's description to the LLM on every call.
The tools still check permissions themselves (the Tester's readFile, for
example, accepts only test files).

stdout carries the MCP messages, so nothing in this process may print to it;
log messages go to stderr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ai_coder.mcp.tools.execution import DEFAULT_TIMEOUT_SECONDS, ExecutionTools
from ai_coder.mcp.tools.files import FileTools
from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage

ROLE_TOOLS: dict[AgentRole, tuple[str, ...]] = {
    AgentRole.PLANNER: ("listFiles", "readFile"),
    AgentRole.CODER: ("listFiles", "readFile", "writeFile"),
    AgentRole.TESTER: ("listFiles", "readFile", "writeFile", "runChecks"),
}

ProjectPath = Annotated[
    str, Field(description="Path relative to the project folder, with '/' separators, e.g. 'playlist.js'.")
]


def create_mcp_server(scope: ToolScope, check_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> FastMCP:
    """Build an MCP server that exposes `scope.role`'s tools for `scope`'s run.

    The docstrings of the inner functions become the tool descriptions the
    LLM reads, so they are written for the model.
    """
    files = FileTools(scope)
    execution = ExecutionTools(scope, timeout_seconds=check_timeout_seconds)

    def list_files(
        directory: Annotated[str, Field(description="Folder to list; '.' for the whole project.")] = ".",
    ) -> dict[str, list[dict[str, Any]]]:
        """List the project's files as {"files": [{path, size in bytes}]}."""
        # Wrapped in an object: MCP would send a bare list as one message per
        # file, and an empty project as no text at all.
        return {"files": files.list_files(directory)}

    def read_file(path: ProjectPath) -> str:
        """Return the text of one project file."""
        return files.read_file(path)

    def write_file(
        path: ProjectPath,
        content: Annotated[str, Field(description="The complete new file content.")],
    ) -> str:
        """Create a project file, or replace its whole content. Missing folders are created."""
        return files.write_file(path, content)

    async def run_checks() -> dict[str, Any]:
        """Run every *.test.js test with node --test and return the real result:
        outcome, passed and failed counts, exit code, and the end of the log."""
        return await execution.run_checks()

    available = {
        "listFiles": list_files,
        "readFile": read_file,
        "writeFile": write_file,
        "runChecks": run_checks,
    }
    server = FastMCP(
        name="ai-coder",
        instructions=(
            f"Tools for the {scope.role.value} of one AI Coder run. "
            "All file paths are relative to the generated project's folder."
        ),
        log_level="WARNING",  # logs go to stderr; keep them to problems only
    )
    for name in ROLE_TOOLS[scope.role]:
        server.add_tool(available[name], name=name)
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the startup arguments that bind this server to one run and role."""
    parser = argparse.ArgumentParser(prog="python -m ai_coder.mcp.server", description=__doc__.splitlines()[0])
    parser.add_argument("--workspaces-root", type=Path, required=True, help="Same root the backend uses.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in AgentRole])
    parser.add_argument("--check-timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds runChecks lets the tests run.")
    return parser.parse_args(argv)


def build_scope(args: argparse.Namespace) -> ToolScope:
    """Turn the startup arguments into a ToolScope, or exit if the run does not exist."""
    root = args.workspaces_root
    if not root.is_dir():
        sys.exit(f"ai-coder MCP server: workspaces root {root} does not exist.")
    storage = FileStorage(root)
    if storage.get_workspace(args.workspace_id) is None or storage.get_run(args.workspace_id, args.run_id) is None:
        sys.exit(f"ai-coder MCP server: run {args.workspace_id}/{args.run_id} does not exist.")
    return ToolScope(
        storage=storage,
        context=RunContext(args.workspace_id, args.run_id),
        role=AgentRole(args.role),
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point: bind the scope from the arguments and serve MCP over stdio."""
    args = parse_args(argv)
    create_mcp_server(build_scope(args), check_timeout_seconds=args.check_timeout).run("stdio")


if __name__ == "__main__":
    main()
