"""Run reads, workspace scope, and startup recovery."""

import pytest
from fastapi.testclient import TestClient

from ai_coder.api.schemas import RunSummary
from ai_coder.config import Settings
from ai_coder.main import create_app
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage
from conftest import assert_error

BODY = {"description": "Music Playlist Mixer", "requirements": ["Pick genres"]}


def create_workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "Demo"}).json()["id"]


def create_run(client, workspace_id, body=BODY):
    run = client.app.state.storage.create_run(workspace_id, body["description"], body["requirements"])
    return RunSummary.of(run).model_dump(by_alias=True, mode="json")


def test_direct_run_creation_route_is_removed(client):
    workspace_id = create_workspace(client)
    response = client.post(f"/api/workspaces/{workspace_id}/runs", json=BODY)
    assert response.status_code == 405


# --- GET /runs -----------------------------------------------------------------------


def test_list_runs_newest_first(client):
    workspace_id = create_workspace(client)
    older = create_run(client, workspace_id)
    newer = create_run(client, workspace_id)
    runs = client.get(f"/api/workspaces/{workspace_id}/runs").json()
    assert [run["id"] for run in runs] == [newer["id"], older["id"]]
    assert set(runs[0]) == {"id", "workspaceId", "status", "createdAt"}


def test_list_runs_of_new_workspace_is_empty(client):
    workspace_id = create_workspace(client)
    assert client.get(f"/api/workspaces/{workspace_id}/runs").json() == []


def test_list_runs_of_missing_workspace_is_404(client):
    assert_error(client.get("/api/workspaces/missing/runs"), 404, "NOT_FOUND")


# --- GET /runs/{runId} ---------------------------------------------------------------


def test_run_detail_shape(client):
    workspace_id = create_workspace(client)
    run = create_run(client, workspace_id)
    detail = client.get(f"/api/workspaces/{workspace_id}/runs/{run['id']}").json()
    assert set(detail) == {
        "id", "workspaceId", "status", "createdAt",
        "activeRole", "error", "checks", "usage",
    }
    assert set(detail["checks"]) == {"build", "tests"}
    assert set(detail["usage"]) == {"apiCalls", "inputTokens", "outputTokens", "totalTokens"}


def test_run_from_another_workspace_is_404(client):
    first = create_workspace(client)
    second = create_workspace(client)
    run = create_run(client, first)
    assert_error(
        client.get(f"/api/workspaces/{second}/runs/{run['id']}"), 404, "NOT_FOUND"
    )


def test_unknown_run_is_404(client):
    workspace_id = create_workspace(client)
    assert_error(client.get(f"/api/workspaces/{workspace_id}/runs/missing"), 404, "NOT_FOUND")


# --- Startup recovery ------------------------------------------------------------------


def test_startup_fails_runs_left_running(tmp_path):
    settings = Settings(workspaces_root=tmp_path / "workspaces")
    storage = FileStorage(settings.workspaces_root)
    workspace = storage.create_workspace("Demo")
    run = storage.create_run(workspace.id, "x", [])
    storage.update_run(
        RunContext(workspace.id, run.id), status="running", active_role=AgentRole.CODER
    )
    with TestClient(create_app(settings)) as client:
        detail = client.get(f"/api/workspaces/{workspace.id}/runs/{run.id}").json()
    assert detail["status"] == "failed"
    assert detail["activeRole"] is None
    assert "restarted" in detail["error"]
