"""HTTP response bodies, exactly as defined in docs/interfaces.md.

These mirror frontend/src/types/index.ts. Field names are snake_case here and
camelCase on the wire (FastAPI serializes response models by alias). Do not add
fields without updating interfaces.md and the frontend types.
"""
from __future__ import annotations

from ai_coder.models import CamelModel


class WorkspaceSummary(CamelModel):
    id: str
    name: str


class WorkspaceDetail(WorkspaceSummary):
    root_path: str
    created_at: str
