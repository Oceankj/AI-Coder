"""HTTP routes; see docs/interfaces.md for the contract.

Routes only validate input, call `FileStorage`, and convert records to the
response schemas in `schemas.py`. They hold no business logic. Behavior
(status codes, error codes, ordering) matches the frontend's MSW handlers in
frontend/src/mocks/handlers.ts so the frontend works against either one.

Implemented so far: workspace routes (step 3). Run routes follow in steps 4-5.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from ai_coder.api.errors import invalid_input, not_found
from ai_coder.api.schemas import WorkspaceDetail, WorkspaceSummary
from ai_coder.config import REPO_ROOT
from ai_coder.models import WorkspaceRecord
from ai_coder.storage.repository import FileStorage

router = APIRouter(prefix="/api")


def storage_of(request: Request) -> FileStorage:
    return request.app.state.storage


def display_root_path(workspaces_root: Path, workspace_id: str) -> str:
    """The workspace directory as shown to the frontend (`rootPath`).

    Repo-relative when the data lives inside the repository (the default,
    "workspaces/<id>", same as MSW); otherwise the absolute path.
    """
    directory = (workspaces_root / workspace_id).resolve()
    try:
        return directory.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return directory.as_posix()


async def read_json_body(request: Request) -> Any:
    """Parse the request body as JSON, or fail with 400 INVALID_INPUT.

    Bodies are parsed by hand rather than declared as FastAPI parameters so
    that checks run in the contract's order (e.g. 404 for a missing workspace
    before 400 for a bad body) and every failure uses our error format.
    """
    try:
        return await request.json()
    except ValueError:
        raise invalid_input("Request body must be valid JSON.") from None


def to_detail(request: Request, record: WorkspaceRecord) -> WorkspaceDetail:
    return WorkspaceDetail(
        id=record.id,
        name=record.name,
        root_path=display_root_path(storage_of(request).root, record.id),
        created_at=record.created_at,
    )


# --- Workspaces -------------------------------------------------------------------


@router.get("/workspaces", response_model=list[WorkspaceSummary])
async def list_workspaces(request: Request) -> list[WorkspaceSummary]:
    """All workspaces, oldest first."""
    return [
        WorkspaceSummary(id=record.id, name=record.name)
        for record in storage_of(request).list_workspaces()
    ]


@router.post("/workspaces", response_model=WorkspaceSummary, status_code=201)
async def create_workspace(request: Request) -> WorkspaceSummary:
    """Create a workspace from {"name": string}; the name is trimmed.

    The backend allocates the ID and directory; the frontend sends only a name.
    """
    body = await read_json_body(request)
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise invalid_input("name must be a nonempty string.")
    record = storage_of(request).create_workspace(name.strip())
    return WorkspaceSummary(id=record.id, name=record.name)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(request: Request, workspace_id: str) -> WorkspaceDetail:
    record = storage_of(request).get_workspace(workspace_id)
    if record is None:
        raise not_found()
    return to_detail(request, record)
