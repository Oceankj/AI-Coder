"""Step 5: events, files, file content, and download routes.

Behavior must match docs/interfaces.md and the frontend's MSW handlers
(frontend/src/mocks/handlers.ts).
"""
import io
import os
import zipfile

import pytest

from ai_coder.models import RunContext
from conftest import assert_error

@pytest.fixture
def storage(client):
    return client.app.state.storage


@pytest.fixture
def workspace_id(client):
    return client.post("/api/workspaces", json={"name": "Demo"}).json()["id"]


@pytest.fixture
def finished_run(storage, idle_run):
    project = storage.project_dir(idle_run)
    (project / "index.html").write_text("<h1>Hello</h1>")
    (project / "package.json").write_text("{}")
    (project / "playlist.js").write_text("export const songs = [];")
    storage.update_run(idle_run, status="completed")
    return idle_run


@pytest.fixture
def idle_run(storage, workspace_id):
    """A queued run that nothing executes (created directly in storage)."""
    run = storage.create_run(workspace_id, "Idle", [])
    return RunContext(workspace_id, run.id)


def url(context, suffix=""):
    return f"/api/workspaces/{context.workspace_id}/runs/{context.run_id}{suffix}"


# --- GET …/events ----------------------------------------------------------------


def test_events_without_cursor_returns_all(client, storage, idle_run):
    storage.append_event(idle_run, "running", "Run started.")
    body = client.get(url(idle_run, "/events")).json()
    assert set(body) == {"events", "nextCursor"}
    assert [e["id"] for e in body["events"]] == [1, 2]
    assert set(body["events"][0]) == {"id", "type", "message", "createdAt"}
    assert body["nextCursor"] == 2


def test_events_after_cursor(client, storage, idle_run):
    storage.append_event(idle_run, "running", "Run started.")
    storage.append_event(idle_run, "role_started", "Planner started.")
    body = client.get(url(idle_run, "/events?after=1")).json()
    assert [e["id"] for e in body["events"]] == [2, 3]
    assert body["nextCursor"] == 3


def test_events_with_no_newer_events_keep_the_cursor(client, idle_run):
    body = client.get(url(idle_run, "/events?after=7")).json()
    assert body == {"events": [], "nextCursor": 7}


def test_empty_cursor_means_zero(client, idle_run):
    # Same as MSW, where Number("") is 0.
    assert client.get(url(idle_run, "/events?after=")).json()["nextCursor"] == 1


@pytest.mark.parametrize("after", ["-1", "1.5", "abc", "1e3", "9007199254740992"])
def test_invalid_cursor_is_400(client, idle_run, after):
    assert_error(client.get(url(idle_run, f"/events?after={after}")), 400, "INVALID_CURSOR")


def test_events_of_missing_run_are_404_before_cursor_check(client, workspace_id):
    response = client.get(f"/api/workspaces/{workspace_id}/runs/missing/events?after=x")
    assert_error(response, 404, "NOT_FOUND")


def test_events_of_run_in_another_workspace_are_404(client, idle_run):
    other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    response = client.get(f"/api/workspaces/{other}/runs/{idle_run.run_id}/events")
    assert_error(response, 404, "NOT_FOUND")


# --- GET …/files ----------------------------------------------------------------------


def test_files_of_new_run_is_empty(client, idle_run):
    assert client.get(url(idle_run, "/files")).json() == []


def test_files_lists_generated_project(client, finished_run):
    files = client.get(url(finished_run, "/files")).json()
    assert [f["path"] for f in files] == [
        "index.html",
        "package.json",
        "playlist.js",
    ]
    assert all(set(f) == {"path", "size", "mediaType"} for f in files)
    media = {f["path"]: f["mediaType"] for f in files}
    assert media["index.html"] == "text/html"
    assert media["package.json"] == "application/json"
    assert media["playlist.js"] == "text/javascript"


def test_file_size_is_in_bytes(client, storage, idle_run):
    (storage.project_dir(idle_run) / "note.txt").write_text("é", encoding="utf-8")
    files = client.get(url(idle_run, "/files")).json()
    assert files == [{"path": "note.txt", "size": 2, "mediaType": "text/plain"}]


def test_files_include_nested_directories(client, storage, idle_run):
    nested = storage.project_dir(idle_run) / "src" / "lib"
    nested.mkdir(parents=True)
    (nested / "util.js").write_text("x")
    paths = [f["path"] for f in client.get(url(idle_run, "/files")).json()]
    assert paths == ["src/lib/util.js"]


def test_files_skip_symlinks(client, storage, idle_run, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    os.symlink(outside, storage.project_dir(idle_run) / "link.txt")
    assert client.get(url(idle_run, "/files")).json() == []


def test_files_of_missing_run_is_404(client, workspace_id):
    assert_error(client.get(f"/api/workspaces/{workspace_id}/runs/missing/files"), 404, "NOT_FOUND")


# --- GET …/file?path= --------------------------------------------------------------------


def test_read_file(client, storage, finished_run):
    response = client.get(url(finished_run, "/file"), params={"path": "index.html"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"path", "size", "mediaType", "content", "encoding"}
    on_disk = (storage.project_dir(finished_run) / "index.html").read_text(encoding="utf-8")
    assert body["content"] == on_disk
    assert body["size"] == len(on_disk.encode("utf-8"))
    assert body["encoding"] == "utf-8"
    assert body["mediaType"] == "text/html"


def test_read_nested_file(client, storage, idle_run):
    (storage.project_dir(idle_run) / "src").mkdir()
    (storage.project_dir(idle_run) / "src" / "a.js").write_text("export {}")
    body = client.get(url(idle_run, "/file"), params={"path": "src/a.js"}).json()
    assert body["content"] == "export {}"


@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "a\\b", "a/../b", "./a", "a//b", "C:x", "..", "a\0b"]
)
def test_invalid_file_paths_are_400(client, idle_run, path):
    response = client.get(url(idle_run, "/file"), params={"path": path})
    assert_error(response, 400, "INVALID_PATH")


def test_missing_path_parameter_is_400(client, idle_run):
    assert_error(client.get(url(idle_run, "/file")), 400, "INVALID_PATH")


def test_missing_file_is_404(client, idle_run):
    response = client.get(url(idle_run, "/file"), params={"path": "nope.js"})
    assert_error(response, 404, "NOT_FOUND")


def test_directory_is_404(client, storage, idle_run):
    (storage.project_dir(idle_run) / "src").mkdir()
    response = client.get(url(idle_run, "/file"), params={"path": "src"})
    assert_error(response, 404, "NOT_FOUND")


def test_symlink_escape_is_400(client, storage, idle_run, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    os.symlink(secret, storage.project_dir(idle_run) / "link.txt")
    response = client.get(url(idle_run, "/file"), params={"path": "link.txt"})
    assert_error(response, 400, "INVALID_PATH")
    assert "secret" not in response.text


def test_file_larger_than_2_mib_is_413(client, storage, idle_run):
    (storage.project_dir(idle_run) / "big.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    response = client.get(url(idle_run, "/file"), params={"path": "big.txt"})
    assert_error(response, 413, "FILE_TOO_LARGE")


def test_file_of_exactly_2_mib_is_allowed(client, storage, idle_run):
    (storage.project_dir(idle_run) / "edge.txt").write_bytes(b"x" * (2 * 1024 * 1024))
    response = client.get(url(idle_run, "/file"), params={"path": "edge.txt"})
    assert response.status_code == 200


def test_non_utf8_file_is_415(client, storage, idle_run):
    (storage.project_dir(idle_run) / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    response = client.get(url(idle_run, "/file"), params={"path": "image.png"})
    assert_error(response, 415, "UNSUPPORTED_FILE")


def test_file_of_missing_run_is_404_before_path_check(client, workspace_id):
    response = client.get(
        f"/api/workspaces/{workspace_id}/runs/missing/file", params={"path": "../x"}
    )
    assert_error(response, 404, "NOT_FOUND")


# --- GET …/download --------------------------------------------------------------------


def test_download_of_unfinished_run_is_409(client, idle_run):
    assert_error(client.get(url(idle_run, "/download")), 409, "NOT_READY")


def test_download_of_failed_run_is_409(client, storage, idle_run):
    storage.update_run(idle_run, status="failed", error="x")
    assert_error(client.get(url(idle_run, "/download")), 409, "NOT_READY")


def test_download_of_missing_run_is_404(client, workspace_id):
    response = client.get(f"/api/workspaces/{workspace_id}/runs/missing/download")
    assert_error(response, 404, "NOT_FOUND")


def test_download_returns_zip_with_project_and_instructions(client, storage, finished_run):
    response = client.get(url(finished_run, "/download"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="{finished_run.run_id}.zip"'
    )
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == [
        "RUNNING.md",
        "index.html",
        "package.json",
        "playlist.js",
    ]
    project = storage.project_dir(finished_run)
    assert archive.read("playlist.js") == (project / "playlist.js").read_bytes()
    instructions = archive.read("RUNNING.md").decode("utf-8")
    assert "node --test" in instructions and "index.html" in instructions


def test_project_running_md_is_not_overwritten(client, storage, finished_run):
    # A generated project that ships its own RUNNING.md keeps it.
    (storage.project_dir(finished_run) / "RUNNING.md").write_text("custom")
    storage.package_run(finished_run)
    archive = zipfile.ZipFile(io.BytesIO(client.get(url(finished_run, "/download")).content))
    assert archive.read("RUNNING.md") == b"custom"


def test_download_packages_lazily_if_zip_is_missing(client, storage, finished_run):
    assert not storage.package_path(finished_run).exists()
    response = client.get(url(finished_run, "/download"))
    assert response.status_code == 200
    assert "index.html" in zipfile.ZipFile(io.BytesIO(response.content)).namelist()
