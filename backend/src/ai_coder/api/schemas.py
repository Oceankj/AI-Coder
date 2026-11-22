# Author: Ching Kao
# Student ID: 85768427
"""HTTP response bodies, exactly as defined in docs/interfaces.md.

These mirror frontend/src/types/index.ts. Field names are snake_case here and
camelCase on the wire (FastAPI serializes response models by alias). Do not add
fields without updating interfaces.md and the frontend types.
"""
from __future__ import annotations

from typing import Literal
from datetime import datetime
from pydantic import Field

from ai_coder.models import (
    AICallCaller,
    AICallEvent,
    AgentRole,
    CamelModel,
    Checks,
    RunEvent,
    RunRecord,
    RunStatus,
    Usage,
)


class WorkspaceSummary(CamelModel):
    id: str
    name: str


class AICallRecord(CamelModel):
    call_id: str
    request_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    event: AICallEvent
    caller: AICallCaller
    role: str | None = None
    model: str | None = None
    resolved_model: str | None = None
    status: int | None = None
    provider_status: int | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    provider_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_code: str | None = None


class WorkspaceDetail(WorkspaceSummary):
    root_path: str
    created_at: str


class RunSummary(CamelModel):
    id: str
    workspace_id: str
    status: RunStatus
    created_at: str

    @classmethod
    def of(cls, run: RunRecord) -> RunSummary:
        return cls(
            id=run.id,
            workspace_id=run.workspace_id,
            status=run.status,
            created_at=run.created_at,
        )


class RunDetail(RunSummary):
    coordinator_report: str | None = Field(default=None, exclude_if=lambda value: value is None)
    active_role: AgentRole | None
    error: str | None
    checks: Checks
    usage: Usage

    @classmethod
    def of(cls, run: RunRecord, usage: Usage) -> RunDetail:  # type: ignore[override]
        return cls(
            **RunSummary.of(run).model_dump(),
            active_role=run.active_role,
            coordinator_report=run.coordinator_report,
            error=run.error,
            checks=run.checks,
            usage=usage,
        )


class RunEvents(CamelModel):
    """One page of events: those with id > the requested cursor."""

    events: list[RunEvent]
    # The last returned event ID, or the requested cursor if none is newer.
    next_cursor: int


class ArtifactFile(CamelModel):
    path: str  # project-relative, "/" separators
    size: int  # bytes, not characters
    media_type: str


class FileContent(ArtifactFile):
    content: str
    encoding: Literal["utf-8"] = "utf-8"
