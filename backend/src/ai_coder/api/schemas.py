"""HTTP response bodies, exactly as defined in docs/interfaces.md.

These mirror frontend/src/types/index.ts. Field names are snake_case here and
camelCase on the wire (FastAPI serializes response models by alias). Do not add
fields without updating interfaces.md and the frontend types.
"""
from __future__ import annotations

from ai_coder.models import AgentRole, CamelModel, Checks, RunRecord, RunStatus, Usage


class WorkspaceSummary(CamelModel):
    id: str
    name: str


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
    active_role: AgentRole | None
    error: str | None
    checks: Checks
    usage: Usage

    @classmethod
    def of(cls, run: RunRecord, usage: Usage) -> RunDetail:  # type: ignore[override]
        return cls(
            **RunSummary.of(run).model_dump(),
            active_role=run.active_role,
            error=run.error,
            checks=run.checks,
            usage=usage,
        )
