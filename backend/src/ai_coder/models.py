# Author: Ching Kao
# Student ID: 85768427
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
from enum import Enum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


from ai_coder.config import Provider


class AgentRole(str, Enum):
    PLANNER = "planner"
    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"


class AICallEvent(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AICallCaller(StrEnum):
    CHAT = "chat"
    AGENT = "agent"


@dataclass(frozen=True)
class RunContext:
    """Identifies one run. Every run-scoped operation takes this pair."""

    workspace_id: str
    run_id: str


RunStatus = Literal["blocked", "queued", "running", "completed", "failed"]
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
    # Repair rounds used so far, across all features (the budget is shared).
    coordinator_report: str | None = Field(default=None, exclude_if=lambda value: value is None)
    continuation: dict | None = Field(default=None, exclude_if=lambda value: value is None)
    repair_count: int = 0
    provider: Provider = Provider.GEMINI
    input: RunInput


# --- events.jsonl (one RunEvent per line) ---------------------------------------


class RunEvent(CamelModel):
    id: int
    type: str
    message: str
    created_at: str
    role: AgentRole | Literal["coordinator"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


# --- usage.json -------------------------------------------------------------------


class Usage(CamelModel):
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


# --- tasks.json --------------------------------------------------------------------


class PlannedFeature(CamelModel):
    """One feature in the Planner's breakdown of the work."""

    title: str  # short name shown in progress events, e.g. "Pick a mood"
    description: str  # what to build and what the tests must check


class TaskFeature(CamelModel):
    """The feature a Coder or Tester task is about."""

    number: int  # 1-based position in the Planner's list
    total: int  # how many features the Planner planned
    title: str
    description: str


class AgentResult(CamelModel):
    """What an agent hands off when it finishes.

    For the Planner, `summary` holds the full plan that the Coder and Tester
    receive, and `features` the ordered list of features to build one at a
    time. Other roles leave `features` empty. `outcome` is the agent's own
    claim; the orchestrator decides whether tests passed from checks.json,
    never from this field.
    """

    summary: str
    artifact_paths: list[str] = Field(default_factory=list)
    outcome: Literal["success", "failure"]
    features: list[PlannedFeature] = Field(default_factory=list)
    submitted_at: str


class AgentTask(CamelModel):
    """One unit of work for one role."""

    id: str  # "<role>-<sequence>", e.g. "coder-3"
    role: AgentRole
    # This role's n-th task in the run (1, 2, 3, ...), across all features
    # and repairs.
    sequence: int
    status: Literal["pending", "submitted"]
    instructions: str
    # Copied from the run input so an agent needs nothing but its task.
    description: str
    requirements: list[str]
    # The Planner's plan; None for the Planner's own task.
    plan: str | None = None
    # The feature to build or test; None for the Planner's task.
    feature: TaskFeature | None = None
    # True when this task repairs (Coder) or re-checks (Tester) a feature
    # whose tests failed.
    repair: bool = False
    # Check output from the failed attempt; set only on Coder repair tasks.
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
