"""Step 4: run routes, end to end with the placeholder agents.

POST creates a run and returns immediately with status "queued"; the run then
executes in the background. Tests poll GET until the run finishes, like the
frontend does.
"""
import time

import pytest
from fastapi.testclient import TestClient

from ai_coder.config import Settings
from ai_coder.main import create_app
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage
from conftest import assert_error, wait_until_finished

BODY = {"description": "Music Playlist Mixer", "requirements": ["Pick genres"]}


def create_workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "Demo"}).json()["id"]


def create_run(client, workspace_id, body=BODY):
    response = client.post(f"/api/workspaces/{workspace_id}/runs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- POST /runs ------------------------------------------------------------------


def test_create_run_returns_queued_summary(client):
    workspace_id = create_workspace(client)
    run = create_run(client, workspace_id)
    assert set(run) == {"id", "workspaceId", "status", "createdAt"}
    assert run["workspaceId"] == workspace_id
    assert run["status"] == "queued"


def test_create_run_for_missing_workspace_is_404(client):
    response = client.post("/api/workspaces/missing/runs", json=BODY)
    assert_error(response, 404, "NOT_FOUND")


def test_missing_workspace_is_checked_before_the_body(client):
    # Same order as the MSW handler: 404 wins over 400.
    response = client.post("/api/workspaces/missing/runs", json={"bad": True})
    assert_error(response, 404, "NOT_FOUND")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"description": "", "requirements": []},
        {"description": "   ", "requirements": []},
        {"description": 1, "requirements": []},
        {"description": "x"},
        {"description": "x", "requirements": "one"},
        {"description": "x", "requirements": [1]},
        {"description": "x", "requirements": None},
        ["x"],
    ],
)
def test_create_run_rejects_invalid_bodies(client, body):
    workspace_id = create_workspace(client)
    response = client.post(f"/api/workspaces/{workspace_id}/runs", json=body)
    assert_error(response, 400, "INVALID_INPUT")


def test_empty_requirements_list_is_allowed(client):
    workspace_id = create_workspace(client)
    create_run(client, workspace_id, {"description": "x", "requirements": []})


def test_create_run_stores_trimmed_description(client, settings):
    workspace_id = create_workspace(client)
    run = create_run(client, workspace_id, {"description": "  Mixer  ", "requirements": []})
    stored = FileStorage(settings.workspaces_root).get_run(workspace_id, run["id"])
    assert stored.input.description == "Mixer"


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


# --- Background execution with placeholder agents -----------------------------------


def test_run_completes_in_the_background(client):
    workspace_id = create_workspace(client)
    run = create_run(client, workspace_id)
    finished = wait_until_finished(client, workspace_id, run["id"])
    assert finished["status"] == "completed"
    assert finished["activeRole"] is None
    assert finished["error"] is None
    assert finished["checks"] == {"build": "not_run", "tests": "passed"}
    # Placeholder agents make no LLM calls.
    assert finished["usage"]["apiCalls"] == 0


def test_placeholder_failures_exercise_the_repair_loop(tmp_path):
    settings = Settings(
        workspaces_root=tmp_path / "workspaces",
        placeholder_delay_seconds=0,
        placeholder_test_failures=1,
    )
    with TestClient(create_app(settings)) as client:
        workspace_id = create_workspace(client)
        run = create_run(client, workspace_id)
        finished = wait_until_finished(client, workspace_id, run["id"])
    assert finished["status"] == "completed"
    stored = FileStorage(settings.workspaces_root).get_run(workspace_id, run["id"])
    assert stored.repair_count == 1


def test_placeholder_failures_beyond_the_limit_fail_the_run(tmp_path):
    settings = Settings(
        workspaces_root=tmp_path / "workspaces",
        max_repairs=1,
        placeholder_delay_seconds=0,
        placeholder_test_failures=5,
    )
    with TestClient(create_app(settings)) as client:
        workspace_id = create_workspace(client)
        run = create_run(client, workspace_id)
        finished = wait_until_finished(client, workspace_id, run["id"])
    assert finished["status"] == "failed"
    assert finished["checks"]["tests"] == "failed"
    assert finished["error"]


# --- Startup recovery ------------------------------------------------------------------


def test_startup_fails_runs_left_running(tmp_path):
    settings = Settings(workspaces_root=tmp_path / "workspaces", placeholder_delay_seconds=0)
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
