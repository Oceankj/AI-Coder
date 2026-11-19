"""Step 4: placeholder agents.

Placeholders stand in for the real agents until stage 4 (Ching) replaces them.
They must follow the same handoff rules as real agents (read their task,
submit a result, the Tester records a check execution) and must say clearly,
in events and logs, that nothing real happened.
"""
import asyncio
import shutil
import subprocess

import pytest

from ai_coder.agents.placeholder import placeholder_agents
from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.orchestrator import Orchestrator
from ai_coder.storage.repository import FileStorage


@pytest.fixture
def storage(tmp_path):
    return FileStorage(tmp_path / "workspaces")


def run_with_placeholders(storage, failures=0, max_repairs=2):
    workspace = storage.create_workspace("Demo")
    run = storage.create_run(workspace.id, "Playlist Mixer", ["Pick a mood"])
    context = RunContext(workspace.id, run.id)
    agents = placeholder_agents(storage, delay_seconds=0, test_failures=failures)
    asyncio.run(Orchestrator(storage, agents, max_repairs=max_repairs).run(context))
    return context


def test_placeholders_complete_a_run(storage):
    context = run_with_placeholders(storage)
    assert storage.get_run(context.workspace_id, context.run_id).status == "completed"


def test_placeholders_write_the_project_files(storage):
    context = run_with_placeholders(storage)
    names = sorted(p.name for p in storage.project_dir(context).iterdir())
    assert names == ["index.html", "package.json", "playlist.js", "playlist.test.js"]


def test_placeholder_events_say_they_are_placeholders(storage):
    context = run_with_placeholders(storage)
    tool_calls = [e for e in storage.list_events(context) if e.type == "tool_call"]
    assert tool_calls, "placeholders should show MCP-like tool calls in the log"
    assert all("placeholder" in e.message.lower() for e in tool_calls)


def test_placeholder_check_execution_is_labelled(storage):
    context = run_with_placeholders(storage)
    execution = storage.list_check_executions(context)[-1]
    assert "placeholder" in execution.command.lower()
    assert "no tests were executed" in execution.log.lower()


def test_placeholder_failures_count_attempts(storage):
    context = run_with_placeholders(storage, failures=2, max_repairs=2)
    outcomes = [e.outcome for e in storage.list_check_executions(context)]
    assert outcomes == ["failed", "failed", "passed"]


def test_placeholder_tasks_get_submitted(storage):
    context = run_with_placeholders(storage)
    for role in AgentRole:
        assert storage.get_current_task(context, role).status == "submitted"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_placeholder_project_really_passes_node_test(storage):
    # The placeholder only *claims* a result, but its files should still be a
    # valid project so later stages can run real checks against them.
    context = run_with_placeholders(storage)
    result = subprocess.run(
        ["node", "--test"],
        cwd=storage.project_dir(context),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
