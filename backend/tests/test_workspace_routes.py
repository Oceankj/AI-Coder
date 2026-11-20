"""Step 3: workspace routes.

Behavior must match docs/interfaces.md and the frontend's MSW handlers
(frontend/src/mocks/handlers.ts), because the frontend switches between the two
without code changes.
"""
import re

import pytest

from ai_coder.api.routes import display_root_path
from ai_coder.config import REPO_ROOT
from conftest import assert_error

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def create(client, name="Demo"):
    response = client.post("/api/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


# --- GET /api/workspaces ---------------------------------------------------------


def test_list_is_empty_array_initially(client):
    response = client.get("/api/workspaces")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    # Lists are bare arrays, not wrapped in {"data": ...}.
    assert response.json() == []


def test_list_returns_summaries_in_creation_order(client):
    first = create(client, "First")
    second = create(client, "Second")
    assert client.get("/api/workspaces").json() == [first, second]


# --- POST /api/workspaces ----------------------------------------------------------


def test_create_returns_201_summary(client):
    response = client.post("/api/workspaces", json={"name": "Demo"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name"}
    assert body["name"] == "Demo"
    assert body["id"]


def test_create_trims_name(client):
    assert create(client, "  Demo  ")["name"] == "Demo"


def test_create_makes_workspace_directory(client, settings):
    workspace = create(client)
    assert (settings.workspaces_root / workspace["id"] / "metadata.json").is_file()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": 42},
        {"name": None},
        ["Demo"],
        "Demo",
    ],
)
def test_create_rejects_invalid_names(client, body):
    response = client.post("/api/workspaces", json=body)
    assert_error(response, 400, "INVALID_INPUT")


def test_create_rejects_non_json_body(client):
    response = client.post(
        "/api/workspaces",
        content=b"name=Demo",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert_error(response, 400, "INVALID_INPUT")


def test_create_rejects_malformed_json(client):
    response = client.post(
        "/api/workspaces",
        content=b'{"name": ',
        headers={"Content-Type": "application/json"},
    )
    assert_error(response, 400, "INVALID_INPUT")


# --- GET /api/workspaces/{workspaceId} ----------------------------------------------


def test_get_returns_detail(client):
    workspace = create(client)
    response = client.get(f"/api/workspaces/{workspace['id']}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "name", "rootPath", "createdAt"}
    assert body["id"] == workspace["id"]
    assert body["name"] == "Demo"
    assert body["rootPath"].endswith(f"workspaces/{workspace['id']}")
    assert TIMESTAMP.match(body["createdAt"])


def test_get_unknown_workspace_is_404(client):
    assert_error(client.get("/api/workspaces/missing"), 404, "NOT_FOUND")


@pytest.mark.parametrize("bad_id", ["bad.id", "..", "%2E%2E", "a%2Fb"])
def test_get_unsafe_id_is_404(client, bad_id):
    assert_error(client.get(f"/api/workspaces/{bad_id}"), 404, "NOT_FOUND")


def test_root_path_is_repo_relative_for_default_root():
    # The default root lives in the repository, so rootPath matches MSW's
    # "workspaces/<id>". Tested on the helper so no test writes into the repo.
    assert display_root_path(REPO_ROOT / "workspaces", "abc") == "workspaces/abc"


def test_root_path_is_absolute_when_root_is_outside_repo(tmp_path):
    # A custom root outside the repo has no meaningful relative form.
    root = tmp_path / "data"
    assert display_root_path(root, "abc") == (root / "abc").as_posix()
