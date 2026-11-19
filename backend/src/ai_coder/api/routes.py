"""HTTP routes; see docs/interfaces.md for the contract.

Routes only validate input, call `FileStorage`, and convert records to the
response schemas in `schemas.py`. They hold no business logic. Behavior
(status codes, error codes, ordering) matches the frontend's MSW handlers in
frontend/src/mocks/handlers.ts so the frontend works against either one.

All ten routes of the contract are implemented: workspaces (step 3), runs
(step 4), and events, files, file content, and download (step 5).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response

from ai_coder.api.errors import ApiError, invalid_input, not_found
from ai_coder.api.schemas import (
    ArtifactFile,
    FileContent,
    RunDetail,
    RunEvents,
    RunSummary,
    WorkspaceDetail,
    WorkspaceSummary,
)
from ai_coder.config import REPO_ROOT
from ai_coder.models import RunContext, RunRecord, WorkspaceRecord
from ai_coder.orchestration.scheduler import RunScheduler
from ai_coder.storage.repository import FileStorage
from ai_coder.workspaces.service import InvalidPathError, resolve_project_path

router = APIRouter(prefix="/api")


def storage_of(request: Request) -> FileStorage:
    return request.app.state.storage


def scheduler_of(request: Request) -> RunScheduler:
    return request.app.state.scheduler


def require_run(request: Request, workspace_id: str, run_id: str) -> RunRecord:
    """The run, or 404 if it is missing or belongs to another workspace."""
    run = storage_of(request).get_run(workspace_id, run_id)
    if run is None:
        raise not_found()
    return run


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


# --- Runs -------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/runs", response_model=list[RunSummary])
async def list_runs(request: Request, workspace_id: str) -> list[RunSummary]:
    """Runs of the workspace, newest first."""
    runs = storage_of(request).list_runs(workspace_id)
    if runs is None:
        raise not_found()
    return [RunSummary.of(run) for run in runs]


@router.post(
    "/workspaces/{workspace_id}/runs", response_model=RunSummary, status_code=201
)
async def create_run(request: Request, workspace_id: str) -> RunSummary:
    """Create a run from {"description": string, "requirements": string[]}.

    Returns at once with status "queued"; generation continues in the
    background and the frontend polls the run for progress.
    """
    storage = storage_of(request)
    # Workspace first: a missing workspace is 404 even when the body is invalid.
    if storage.get_workspace(workspace_id) is None:
        raise not_found()
    body = await read_json_body(request)
    if not isinstance(body, dict):
        raise invalid_input("Request body must be a JSON object.")
    description = body.get("description")
    requirements = body.get("requirements")
    if (
        not isinstance(description, str)
        or not description.strip()
        or not isinstance(requirements, list)
        or not all(isinstance(item, str) for item in requirements)
    ):
        raise invalid_input(
            "Provide a description string and a requirements array of strings."
        )
    run = storage.create_run(workspace_id, description.strip(), requirements)
    # The summary is built before the background task can change the status.
    summary = RunSummary.of(run)
    scheduler_of(request).submit(RunContext(workspace_id, run.id))
    return summary


@router.get("/workspaces/{workspace_id}/runs/{run_id}", response_model=RunDetail)
async def get_run(request: Request, workspace_id: str, run_id: str) -> RunDetail:
    """Status, active role, error, checks, and usage of one run."""
    run = require_run(request, workspace_id, run_id)
    usage = storage_of(request).get_usage(RunContext(workspace_id, run_id))
    return RunDetail.of(run, usage)


# --- Events, files, and download ----------------------------------------------------

# The largest event cursor JavaScript can represent exactly (Number.MAX_SAFE_INTEGER).
MAX_CURSOR = 2**53 - 1
# File previews are bounded to 2 MiB of UTF-8 text (docs/interfaces.md).
MAX_PREVIEW_BYTES = 2 * 1024 * 1024

# Media types by extension; anything else is plain text.
MEDIA_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
}


def media_type_for(path: str) -> str:
    return MEDIA_TYPES.get(Path(path).suffix.lower(), "text/plain")


def parse_cursor(raw: str | None) -> int:
    """The events `after` cursor: a nonnegative integer; missing or empty is 0.

    Mirrors MSW, where Number("") is 0. Signs, decimals, exponents, and values
    beyond JavaScript's safe integer range are rejected.
    """
    if raw is None or raw == "":
        return 0
    if not raw.isascii() or not raw.isdigit() or int(raw) > MAX_CURSOR:
        raise ApiError(400, "INVALID_CURSOR", "after must be a nonnegative integer.")
    return int(raw)


@router.get(
    "/workspaces/{workspace_id}/runs/{run_id}/events", response_model=RunEvents
)
async def list_events(request: Request, workspace_id: str, run_id: str) -> RunEvents:
    """Events with id > `after`, oldest first; the frontend polls with nextCursor."""
    require_run(request, workspace_id, run_id)  # 404 before validating the cursor
    after = parse_cursor(request.query_params.get("after"))
    events = storage_of(request).list_events(RunContext(workspace_id, run_id), after)
    return RunEvents(events=events, next_cursor=events[-1].id if events else after)


@router.get(
    "/workspaces/{workspace_id}/runs/{run_id}/files", response_model=list[ArtifactFile]
)
async def list_files(request: Request, workspace_id: str, run_id: str) -> list[ArtifactFile]:
    """Every regular file in the run's project, sorted by path (symlinks skipped)."""
    require_run(request, workspace_id, run_id)
    files = storage_of(request).list_project_files(RunContext(workspace_id, run_id))
    return [
        ArtifactFile(path=file.path, size=file.size, media_type=media_type_for(file.path))
        for file in files
    ]


@router.get(
    "/workspaces/{workspace_id}/runs/{run_id}/file", response_model=FileContent
)
async def read_file(request: Request, workspace_id: str, run_id: str) -> FileContent:
    """Text content of one project file, read-only.

    Errors: 400 INVALID_PATH (bad syntax, or a symlink pointing outside the
    project), 404 (missing file or a directory), 413 (over 2 MiB), 415 (not
    UTF-8).
    """
    require_run(request, workspace_id, run_id)  # 404 before validating the path
    path = request.query_params.get("path") or ""
    project = storage_of(request).project_dir(RunContext(workspace_id, run_id))
    try:
        resolved = resolve_project_path(project, path)
    except InvalidPathError as error:
        raise ApiError(400, "INVALID_PATH", f"Provide a valid project-relative path. {error}") from None
    if not resolved.is_file():
        raise not_found()
    size = resolved.stat().st_size
    if size > MAX_PREVIEW_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "File exceeds the 2 MiB preview limit.")
    try:
        content = resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ApiError(415, "UNSUPPORTED_FILE", "Only UTF-8 text files can be previewed.") from None
    return FileContent(
        path=path, size=size, media_type=media_type_for(path), content=content
    )


@router.get("/workspaces/{workspace_id}/runs/{run_id}/download")
async def download(request: Request, workspace_id: str, run_id: str) -> Response:
    """The completed run's project as a ZIP (with RUNNING.md instructions).

    Only completed runs can be downloaded (409 otherwise, as in MSW). The ZIP
    is normally written when the run completes; it is rebuilt here if missing.
    """
    run = require_run(request, workspace_id, run_id)
    if run.status != "completed":
        raise ApiError(409, "NOT_READY", "Run is not complete yet.")
    storage = storage_of(request)
    context = RunContext(workspace_id, run_id)
    zip_path = storage.package_path(context)
    if not zip_path.is_file():
        zip_path = storage.package_run(context)
    return Response(
        content=zip_path.read_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )
