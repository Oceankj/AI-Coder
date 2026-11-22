# Author: Shih-Yun Huang
# Student ID: 20645816
"""Tester-only MCP interface to the shared project test runner."""
from typing import Any

from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import AgentRole
from ai_coder.workspaces.checks import DEFAULT_TIMEOUT_SECONDS, run_checks
from ai_coder.workspaces.permissions import PermissionDeniedError

MAX_LOG_FOR_MODEL_CHARS = 4_000


class ExecutionTools:
    def __init__(self, scope: ToolScope, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.scope = scope
        self.timeout_seconds = timeout_seconds

    async def run_checks(self) -> dict[str, Any]:
        if self.scope.role is not AgentRole.TESTER:
            raise PermissionDeniedError(
                f"Only the Tester runs checks; the {self.scope.role.value} may not call runChecks."
            )
        execution = await run_checks(
            self.scope.storage, self.scope.context, timeout_seconds=self.timeout_seconds
        )
        if execution.exit_code is None and not execution.timed_out:
            raise RuntimeError(execution.log)
        return {
            "outcome": execution.outcome,
            "passed": execution.passed,
            "failed": execution.failed,
            "exitCode": execution.exit_code,
            "timedOut": execution.timed_out,
            "log": execution.log[-MAX_LOG_FOR_MODEL_CHARS:],
        }
