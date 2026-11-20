"""Shared fixtures for API tests."""
import pytest
from fastapi.testclient import TestClient

from ai_coder.config import Settings
from ai_coder.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings that keep all runtime data inside the test's temporary folder."""
    return Settings(workspaces_root=tmp_path / "workspaces", placeholder_delay_seconds=0)


@pytest.fixture
def client(settings):
    # The context manager runs the app's startup and shutdown hooks.
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def assert_error(response, status: int, code: str) -> None:
    """Assert the uniform error shape from docs/interfaces.md."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def wait_until_finished(client, workspace_id, run_id, timeout=5.0):
    """Poll the run like the frontend does, until it completes or fails."""
    import time

    deadline = time.monotonic() + timeout
    run = None
    while time.monotonic() < deadline:
        run = client.get(f"/api/workspaces/{workspace_id}/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.02)
    raise AssertionError(f"Run did not finish within {timeout}s: {run}")
