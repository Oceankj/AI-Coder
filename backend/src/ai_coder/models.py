"""Shared models.

Two kinds of types live here:

- Small value types used everywhere (`AgentRole`, `RunContext`).
- Records stored in the run directory (`RunRecord`, `AgentTask`, ...). Their
  JSON form is a contract with the MCP server (stage 3) and the agents
  (stage 4), documented in docs/backend-spec.md. Python attributes are
  snake_case; JSON keys are camelCase, matching the HTTP API.

Timestamps are ISO 8601 UTC strings with millisecond precision, e.g.
"2026-11-18T08:00:01.000Z" (the same format as JavaScript's toISOString).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"


@dataclass(frozen=True)
class RunContext:
    """Identifies one run. Every run-scoped operation takes this pair."""

    workspace_id: str
    run_id: str


RunStatus = Literal["queued", "running", "completed", "failed"]
CheckStatus = Literal["not_run", "passed", "failed"]


def format_timestamp(moment: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with milliseconds and a Z suffix."""
    utc = moment.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CamelModel(BaseModel):
    """Base for stored records: snake_case in Python, camelCase in JSON."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
    )

    def to_json(self) -> dict[str, Any]:
        """The camelCase JSON-compatible form written to disk."""
        return self.model_dump(mode="json", by_alias=True)


# --- metadata.json ----------------------------------------------------------


class WorkspaceRecord(CamelModel):
    id: str
    name: str
    created_at: str


# --- run.json -----------------------------------------------------------------


class RunInput(CamelModel):
    """What the user submitted when creating the run."""

    description: str
    requirements: list[str]


class Checks(CamelModel):
    # The generated app has no build step, so `build` stays "not_run".
    build: CheckStatus = "not_run"
    tests: CheckStatus = "not_run"


class RunRecord(CamelModel):
    id: str
    workspace_id: str
    status: RunStatus
    created_at: str
    active_role: AgentRole | None = None
    error: str | None = None
    checks: Checks = Field(default_factory=Checks)
    # Completed Coder -> Tester repair rounds (not counting the first attempt).
    repair_count: int = 0
    input: RunInput


# --- events.jsonl (one RunEvent per line) ---------------------------------------


class RunEvent(CamelModel):
    id: int
    type: str
    message: str
    created_at: str


# --- usage.json -------------------------------------------------------------------


class Usage(CamelModel):
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


# --- tasks.json --------------------------------------------------------------------


class AgentResult(CamelModel):
    """What an agent hands off when it finishes (MCP `submitResult`).

    For the Planner, `summary` holds the full plan that the Coder and Tester
    receive. `outcome` is the agent's own claim; the orchestrator decides
    whether tests passed from checks.json, never from this field.
    """

    summary: str
    artifact_paths: list[str] = Field(default_factory=list)
    outcome: Literal["success", "failure"]
    submitted_at: str


class AgentTask(CamelModel):
    """One unit of work for one role (MCP `getTask` returns the latest one)."""

    id: str  # "<role>-<attempt>", e.g. "coder-2"
    role: AgentRole
    attempt: int  # 1 for the first task of this role, 2 for the first repair...
    status: Literal["pending", "submitted"]
    instructions: str
    # Copied from the run input so an agent needs nothing but its task.
    description: str
    requirements: list[str]
    # The Planner's plan; None for the Planner's own task.
    plan: str | None = None
    # Check output from the failed attempt; set only on repair tasks.
    previous_failure: str | None = None
    created_at: str
    result: AgentResult | None = None


# --- checks.json -------------------------------------------------------------------


class CheckExecution(CamelModel):
    """One real test execution recorded by MCP `runChecks`."""

    id: int
    command: str
    started_at: str
    finished_at: str
    exit_code: int | None  # None when the process was killed by the timeout
    timed_out: bool
    passed: int
    failed: int
    outcome: Literal["passed", "failed"]
    log: str  # tail of stdout + stderr, bounded in size
