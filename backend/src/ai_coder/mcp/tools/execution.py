# Author: Shih-Yun Huang
# Student ID: 20645816
"""Execution tool: runChecks.

runChecks runs the generated tests with Node's built-in test runner and records
the real result in checks.json. The orchestrator decides whether a feature
passed from that record only, never from what an agent says.

The agent cannot choose the command; it is fixed here:

    node --permission --allow-fs-read=<project> --allow-fs-write=<project>
         --test --test-isolation=none --test-reporter=tap "**/*.test.js"

Why each part is there:

- "**/*.test.js": run only test files. Without it, node --test also runs
  files such as test/x.js or x-test.js, which the Coder may write, so the
  Coder could add tests of its own.
- --permission with --allow-fs-read/--allow-fs-write limited to the project:
  the tests are code written by an LLM and run on our machine. Node's
  permission model stops them from reading or writing files outside the
  project and from starting other programs.
- --test-isolation=none: run all test files in this one process, so the
  permission limits above apply to every test.
- --test-reporter=tap: the output ends with "# pass N" and "# fail N" lines
  that are easy to count.
- A minimal environment (PATH only): tests cannot read secrets such as
  GEMINI_API_KEY from process.env, and NODE_OPTIONS cannot switch the
  limits off.
- A timeout: a test stuck in an endless loop is killed.

Requires Node.js 22.13 or later (stable permission model and test isolation).
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any

from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import AgentRole, format_timestamp
from ai_coder.workspaces.permissions import TEST_FILE_SUFFIX, PermissionDeniedError, is_test_file

DEFAULT_TIMEOUT_SECONDS = 60.0

# Keep only the end of the output: the runner prints its summary last, and an
# endless print loop must not fill memory.
MAX_OUTPUT_CHARS = 20_000

# The model receives a shorter tail than checks.json keeps, to save tokens.
MAX_LOG_FOR_MODEL_CHARS = 4_000

# What checks.json records as the command (the project path is left out).
COMMAND_LABEL = (
    "node --permission --allow-fs-read=<project> --allow-fs-write=<project> "
    f'--test --test-isolation=none --test-reporter=tap "**/*{TEST_FILE_SUFFIX}"'
)


class ExecutionTools:
    """runChecks for the role bound in `scope`."""

    def __init__(self, scope: ToolScope, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """Bind the tool to one run and role, with a time limit for the tests."""
        self.scope = scope
        self.timeout_seconds = timeout_seconds

    async def run_checks(self) -> dict[str, Any]:
        """Run every test in the project, record the result, and return it.

        Returns {"outcome", "passed", "failed", "exitCode", "timedOut", "log"};
        "log" is the end of the test output. Only the Tester may run checks.
        """
        self._check_can_run()
        project = self.scope.project_dir.resolve()
        started_at = _now()
        exit_code, timed_out, output = await self._run_node(project)
        finished_at = _now()

        counts = _parse_tap_counts(output)
        failed = counts["fail"] + counts["cancelled"]

        execution = self.scope.storage.append_check_execution(
            self.scope.context,
            command=COMMAND_LABEL,
            exit_code=exit_code,
            timed_out=timed_out,
            passed=counts["pass"],
            failed=failed,
            log=output,
            started_at=started_at,
            finished_at=finished_at,
        )
        return {
            "outcome": execution.outcome,
            "passed": execution.passed,
            "failed": execution.failed,
            "exitCode": execution.exit_code,
            "timedOut": execution.timed_out,
            "log": output[-MAX_LOG_FOR_MODEL_CHARS:],
        }

    def _check_can_run(self) -> None:
        """Raise unless the caller is the Tester and at least one test file exists."""
        if self.scope.role is not AgentRole.TESTER:
            raise PermissionDeniedError(
                f"Only the Tester runs checks; the {self.scope.role.value} may not call runChecks."
            )
        files = self.scope.storage.list_project_files(self.scope.context)
        if not any(is_test_file(file.path) for file in files):
            raise ValueError(
                f"No test files (*{TEST_FILE_SUFFIX}) exist yet. Write tests with writeFile, "
                "then call runChecks."
            )

    async def _run_node(self, project) -> tuple[int | None, bool, str]:
        """Run the fixed node command in `project`.

        Returns (exit code, timed out, output tail). The exit code is None when
        the timeout killed the process.
        """
        command = [
            "node",
            "--permission",
            f"--allow-fs-read={project}",
            f"--allow-fs-write={project}",
            "--test",
            "--test-isolation=none",
            "--test-reporter=tap",
            f"**/*{TEST_FILE_SUFFIX}",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=project,
                env={"PATH": os.environ.get("PATH", "")},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # one combined log
            )
        except FileNotFoundError:
            raise RuntimeError("Node.js ('node') was not found on PATH; install Node.js 22.13 or later.") from None

        tail = _OutputTail(MAX_OUTPUT_CHARS)
        timed_out = False
        try:
            await asyncio.wait_for(tail.collect(process.stdout), self.timeout_seconds)
            exit_code = await process.wait()
        except asyncio.TimeoutError:
            timed_out = True
            exit_code = None
            tail.add(f"\n[runChecks] Stopped: the tests ran longer than {self.timeout_seconds:g} seconds.\n")
        finally:
            # Also runs when the agent itself is cancelled: never leave node running.
            if process.returncode is None:
                process.kill()
                await process.wait()
        return exit_code, timed_out, tail.text()


class _OutputTail:
    """Keeps the last `limit` characters of a process's output."""

    def __init__(self, limit: int) -> None:
        """Start with an empty buffer that holds at most `limit` characters."""
        self.limit = limit
        self._text = ""

    def add(self, chunk: str) -> None:
        """Append `chunk`, dropping the oldest text beyond the limit."""
        self._text = (self._text + chunk)[-self.limit :]

    async def collect(self, stream: asyncio.StreamReader) -> None:
        """Read `stream` until it closes. What was read stays available on timeout."""
        while chunk := await stream.read(4096):
            self.add(chunk.decode("utf-8", errors="replace"))

    def text(self) -> str:
        """The collected output."""
        return self._text


_SUMMARY_LINE = re.compile(r"^# (pass|fail|cancelled) (\d+)\s*$", re.MULTILINE)


def _parse_tap_counts(output: str) -> dict[str, int]:
    """Read the "# pass/fail/cancelled N" summary lines of TAP output.

    Counts that are missing (for example, the process was killed before the
    summary) are 0; the exit code and timeout still mark such a run as failed.
    """
    counts = {"pass": 0, "fail": 0, "cancelled": 0}
    for name, value in _SUMMARY_LINE.findall(output):
        counts[name] = int(value)  # the last summary wins
    return counts


def _now() -> str:
    """The current time in the timestamp format used by the run files."""
    return format_timestamp(datetime.now(timezone.utc))
