"""Step 5: project-relative path validation.

The HTTP file route uses these checks now; stage 3's MCP file tools must use
the same ones (docs/backend-spec.md, "Project paths"). The syntax rules match
docs/interfaces.md and the frontend MSW handler; the symlink rule is the extra
filesystem check that only a real backend can do.
"""
import os

import pytest

from ai_coder.workspaces.service import InvalidPathError, resolve_project_path, validate_relative_path


@pytest.mark.parametrize(
    "path",
    ["index.html", "src/playlist.js", "a/b/c.test.js", ".gitignore", "name with spaces.txt"],
)
def test_valid_paths(path):
    assert validate_relative_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",  # empty
        "/etc/passwd",  # absolute
        "C:/Windows",  # drive prefix
        "c:file",  # drive-relative
        "a\\b",  # backslash
        "a\0b",  # NUL byte
        ".",  # dot segment
        "./index.html",
        "..",  # traversal
        "../secret",
        "a/../b",
        "a//b",  # empty segment
        "a/",  # trailing slash = empty segment
    ],
)
def test_invalid_paths(path):
    with pytest.raises(InvalidPathError):
        validate_relative_path(path)


def test_resolve_stays_inside_project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.js").write_text("x")
    assert resolve_project_path(project, "src/a.js") == (project / "src" / "a.js").resolve()


def test_resolve_allows_missing_files(tmp_path):
    # Writers (MCP writeFile) resolve paths that do not exist yet.
    project = tmp_path / "project"
    project.mkdir()
    assert resolve_project_path(project, "new/file.js") == (project / "new" / "file.js").resolve()


def test_symlinked_file_escaping_the_project_is_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    os.symlink(secret, project / "link.txt")
    with pytest.raises(InvalidPathError):
        resolve_project_path(project, "link.txt")


def test_symlinked_directory_escaping_the_project_is_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, project / "dir")
    with pytest.raises(InvalidPathError):
        resolve_project_path(project, "dir/secret.txt")


def test_symlink_inside_the_project_is_allowed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "real.txt").write_text("x")
    os.symlink(project / "real.txt", project / "alias.txt")
    assert resolve_project_path(project, "alias.txt") == (project / "real.txt").resolve()
