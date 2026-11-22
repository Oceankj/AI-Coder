# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""Stage 3, step 2: the MCP tools as plain Python (no MCP transport yet).

listFiles, readFile, and writeFile are tested directly
against a real run directory created by FileStorage, the same way the MCP
server will call them in step 4.
"""
import os

import pytest

from ai_coder.mcp.tools.files import MAX_FILE_BYTES, FileTools
from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage
from ai_coder.workspaces.permissions import PermissionDeniedError
from ai_coder.workspaces.service import InvalidPathError

PLANNER, CODER, TESTER = AgentRole.PLANNER, AgentRole.CODER, AgentRole.TESTER


@pytest.fixture
def storage(tmp_path):
    """A FileStorage rooted in the test's temporary folder."""
    return FileStorage(tmp_path / "workspaces")


@pytest.fixture
def context(storage):
    """A fresh run with an empty project/ folder."""
    workspace = storage.create_workspace("Test")
    run = storage.create_run(workspace.id, "Music Playlist Mixer", ["Pick genres", "Pick a mood"])
    return RunContext(workspace.id, run.id)


def tools(storage, context, role):
    """Build the file tools for one role, as the server will."""
    return FileTools(ToolScope(storage, context, role))


# --- listFiles / readFile / writeFile ----------------------------------------------


def test_coder_writes_then_reads_a_file(storage, context):
    """writeFile creates parent folders; readFile returns the same text."""
    files = tools(storage, context, CODER)

    assert files.write_file("src/playlist.js", "export const x = 1;\n") == "Wrote src/playlist.js (20 bytes)."
    assert files.read_file("src/playlist.js") == "export const x = 1;\n"
    assert (storage.project_dir(context) / "src/playlist.js").is_file()


def test_list_files_whole_project_and_one_folder(storage, context):
    """listFiles lists every file, or only those under a folder."""
    files = tools(storage, context, CODER)
    files.write_file("index.html", "<h1>Hi</h1>")
    files.write_file("src/playlist.js", "x")

    assert files.list_files() == [
        {"path": "index.html", "size": 11},
        {"path": "src/playlist.js", "size": 1},
    ]
    assert files.list_files("src") == [{"path": "src/playlist.js", "size": 1}]
    assert files.list_files("src/") == [{"path": "src/playlist.js", "size": 1}]


def test_list_files_rejects_bad_folder(storage, context):
    """The folder argument goes through the same path rules."""
    files = tools(storage, context, CODER)
    with pytest.raises(InvalidPathError):
        files.list_files("../other-run")


def test_tester_sees_names_but_cannot_read_source(storage, context):
    """Black-box testing: the Tester knows playlist.js exists, not what is in it."""
    coder_files = tools(storage, context, CODER)
    coder_files.write_file("playlist.js", "secret")
    tester_files = tools(storage, context, TESTER)

    assert {"path": "playlist.js", "size": 6} in tester_files.list_files()
    with pytest.raises(PermissionDeniedError):
        tester_files.read_file("playlist.js")
    tester_files.write_file("mix.test.js", "test")
    assert tester_files.read_file("mix.test.js") == "test"


def test_coder_cannot_edit_tests(storage, context):
    """Tests are the spec: the Coder may read them but not change them."""
    tester_files = tools(storage, context, TESTER)
    tester_files.write_file("mix.test.js", "test")
    coder_files = tools(storage, context, CODER)

    assert coder_files.read_file("mix.test.js") == "test"
    with pytest.raises(PermissionDeniedError):
        coder_files.write_file("mix.test.js", "changed")


def test_planner_cannot_write(storage, context):
    """The Planner only plans."""
    files = tools(storage, context, PLANNER)
    with pytest.raises(PermissionDeniedError):
        files.write_file("plan.md", "plan")


def test_read_missing_file_says_how_to_recover(storage, context):
    """A missing file points the model at listFiles."""
    files = tools(storage, context, CODER)
    with pytest.raises(FileNotFoundError, match="Call listFiles"):
        files.read_file("nope.js")


@pytest.mark.parametrize("path", ["../run.json", "/etc/passwd", "a/../b.js"])
def test_paths_cannot_leave_the_project(storage, context, path):
    """run.json sits next to project/, but no path may reach it."""
    files = tools(storage, context, CODER)
    with pytest.raises(InvalidPathError):
        files.read_file(path)
    with pytest.raises(InvalidPathError):
        files.write_file(path, "x")


def test_symlink_out_of_the_project_is_refused(storage, context):
    """A symlink inside project/ that points outside cannot be read or written."""
    outside = storage.run_dir(context) / "tasks.json"
    os.symlink(outside, storage.project_dir(context) / "link.js")
    files = tools(storage, context, CODER)
    with pytest.raises(InvalidPathError):
        files.read_file("link.js")
    with pytest.raises(InvalidPathError):
        files.write_file("link.js", "x")


def test_size_limits(storage, context):
    """Oversized writes are refused, and so are reads of oversized files."""
    files = tools(storage, context, CODER)
    with pytest.raises(ValueError, match="larger than"):
        files.write_file("big.js", "x" * (MAX_FILE_BYTES + 1))
    (storage.project_dir(context) / "big.js").write_text("x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="larger than"):
        files.read_file("big.js")


def test_binary_file_is_not_returned_as_text(storage, context):
    """Non-UTF-8 content gets a readable error instead of a crash."""
    (storage.project_dir(context) / "logo.png").write_bytes(b"\x89PNG\xff\xfe")
    files = tools(storage, context, CODER)
    with pytest.raises(ValueError, match="not a UTF-8 text file"):
        files.read_file("logo.png")


def test_cannot_write_over_a_folder(storage, context):
    """Writing to a path that is a folder fails clearly."""
    (storage.project_dir(context) / "src").mkdir()
    files = tools(storage, context, CODER)
    with pytest.raises(IsADirectoryError):
        files.write_file("src", "x")
