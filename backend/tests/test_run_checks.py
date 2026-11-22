# Author: Shih-Yun Huang
# Student ID: 20645816
"""Stage 3, step 3: the runChecks tool.

These tests run the real `node --test` on small generated projects, so they
need Node.js 22.13 or later; they are skipped when node is not installed.
"""
import asyncio
import shutil

import pytest

from ai_coder.mcp.tools.execution import ExecutionTools
from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage
from ai_coder.workspaces.checks import _parse_tap_counts, run_checks as run_project_checks
from ai_coder.workspaces.permissions import PermissionDeniedError

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")

TEST_HEADER = 'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'


@pytest.fixture
def storage(tmp_path):
    """A FileStorage rooted in the test's temporary folder."""
    return FileStorage(tmp_path / "workspaces")


@pytest.fixture
def context(storage):
    """A run whose project already has package.json and a small module."""
    workspace = storage.create_workspace("Test")
    run = storage.create_run(workspace.id, "Music Playlist Mixer", ["Mix songs"])
    context = RunContext(workspace.id, run.id)
    project = storage.project_dir(context)
    (project / "package.json").write_text('{"type": "module"}\n')
    (project / "playlist.js").write_text("export const add = (a, b) => a + b;\n")
    return context


def write(storage, context, path, text):
    """Write a file into the run's project (as the Coder or Tester would)."""
    target = storage.project_dir(context) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def run_checks(storage, context, role=AgentRole.TESTER, timeout=30.0):
    """Call runChecks the way the MCP server will, and wait for the result."""
    tools = ExecutionTools(ToolScope(storage, context, role), timeout_seconds=timeout)
    return asyncio.run(tools.run_checks())


def test_passing_tests_are_recorded(storage, context):
    """All tests pass: the result and checks.json both say "passed"."""
    write(storage, context, "add.test.js", TEST_HEADER + (
        'import { add } from "./playlist.js";\n'
        'test("adds", () => assert.equal(add(1, 2), 3));\n'
        'test("adds zero", () => assert.equal(add(0, 2), 2));\n'
    ))

    result = run_checks(storage, context)

    assert result["outcome"] == "passed"
    assert (result["passed"], result["failed"], result["exitCode"], result["timedOut"]) == (2, 0, 0, False)
    [execution] = storage.list_check_executions(context)
    assert execution.outcome == "passed" and execution.passed == 2
    assert "--test-isolation=none" in execution.command


def test_failing_test_is_recorded_with_its_output(storage, context):
    """One failing test makes the run fail, and the log shows which one."""
    write(storage, context, "add.test.js", TEST_HEADER + (
        'import { add } from "./playlist.js";\n'
        'test("adds", () => assert.equal(add(1, 2), 3));\n'
        'test("wrong", () => assert.equal(add(1, 2), 4));\n'
    ))

    result = run_checks(storage, context)

    assert result["outcome"] == "failed"
    assert (result["passed"], result["failed"]) == (1, 1)
    assert "not ok 2 - wrong" in result["log"]
    assert storage.list_check_executions(context)[0].outcome == "failed"


def test_only_test_js_files_run(storage, context):
    """Files node would also treat as tests (test/x.js, x-test.js) are ignored."""
    write(storage, context, "real.test.js", TEST_HEADER + 'test("real", () => {});\n')
    write(storage, context, "test/sneaky.js", TEST_HEADER + 'test("sneaky", () => {});\n')
    write(storage, context, "also-test.js", TEST_HEADER + 'test("also", () => {});\n')

    result = run_checks(storage, context)

    assert result["passed"] == 1
    assert "sneaky" not in result["log"] and "also" not in result["log"]


def test_tests_cannot_touch_files_outside_the_project(storage, context, tmp_path):
    """Node's permission model blocks reads and writes outside project/."""
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    escaped = tmp_path / "escaped.txt"
    write(storage, context, "escape.test.js", TEST_HEADER + (
        'import fs from "node:fs";\n'
        f'test("read outside", () => fs.readFileSync({str(secret)!r}));\n'
        f'test("write outside", () => fs.writeFileSync({str(escaped)!r}, "x"));\n'
    ))

    result = run_checks(storage, context)

    assert result["failed"] == 2
    assert "ERR_ACCESS_DENIED" in result["log"]
    assert "top secret" not in result["log"]
    assert not escaped.exists()


def test_tests_cannot_read_secrets_from_the_environment(storage, context, monkeypatch):
    """Only PATH is passed on, so an API key in the backend's environment stays hidden."""
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-leak")
    write(storage, context, "env.test.js", TEST_HEADER + (
        'test("no key", () => assert.equal(process.env.GEMINI_API_KEY, undefined));\n'
    ))

    result = run_checks(storage, context)

    assert result["outcome"] == "passed"


def test_endless_test_is_stopped_by_the_timeout(storage, context):
    """A stuck test is killed; the execution is recorded as timed out and failed."""
    write(storage, context, "loop.test.js", TEST_HEADER + 'test("forever", () => { while (true) {} });\n')

    result = run_checks(storage, context, timeout=2)

    assert result["timedOut"] is True
    assert result["exitCode"] is None
    assert result["outcome"] == "failed"
    assert "ran longer than 2 seconds" in result["log"]
    assert storage.list_check_executions(context)[0].timed_out is True


def test_no_test_files_is_refused_and_not_recorded(storage, context):
    """Running nothing must not count as a pass."""
    with pytest.raises(ValueError, match="No test files"):
        run_checks(storage, context)
    assert storage.list_check_executions(context) == []


@pytest.mark.parametrize("role", [AgentRole.PLANNER, AgentRole.CODER])
def test_only_the_tester_runs_checks(storage, context, role):
    """The orchestrator reads the check the Tester recorded; others may not add one."""
    write(storage, context, "a.test.js", TEST_HEADER + 'test("a", () => {});\n')
    with pytest.raises(PermissionDeniedError, match="Only the Tester runs checks"):
        run_checks(storage, context, role=role)


def test_missing_node_gives_a_readable_error(storage, context, monkeypatch, tmp_path):
    """Without node on PATH the tool explains what to install."""
    write(storage, context, "a.test.js", TEST_HEADER + 'test("a", () => {});\n')
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    with pytest.raises(RuntimeError, match="Node.js \\('node'\\) was not found"):
        run_checks(storage, context)


def test_parse_tap_counts():
    """The summary lines are read; missing ones count as 0."""
    output = "ok 1 - a\nnot ok 2 - b\n# tests 2\n# pass 1\n# fail 1\n# cancelled 0\n# duration_ms 3.2\n"
    assert _parse_tap_counts(output) == {"pass": 1, "fail": 1, "cancelled": 0}
    assert _parse_tap_counts("killed before the summary") == {"pass": 0, "fail": 0, "cancelled": 0}

def test_runner_returns_distinct_persisted_red_and_green_results(storage, context):
    write(storage, context, "feature.test.js", TEST_HEADER + (
        'import { enabled } from "./feature.js";\n'
        'test("feature is enabled", () => assert.equal(enabled(), true));\n'
    ))
    write(storage, context, "feature.js", "export const enabled = () => false;")
    red = asyncio.run(run_project_checks(storage, context))
    write(storage, context, "feature.js", "export const enabled = () => true;")
    green = asyncio.run(run_project_checks(storage, context))

    assert red.outcome == "failed" and green.outcome == "passed"
    assert red.id != green.id
    assert storage.list_check_executions(context) == [red, green]
