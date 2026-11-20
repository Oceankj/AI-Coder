"""Project-relative path rules, shared by the HTTP API and the MCP file tools.

Every file path that comes from outside (a browser request or an agent's tool
call) is relative to a run's `project/` directory and goes through two checks:

1. `validate_relative_path`: syntax only. Rejects empty paths, absolute paths,
   drive prefixes ("C:"), backslashes, NUL bytes, and empty, "." or ".."
   segments. These are the rules in docs/interfaces.md and the frontend's MSW
   handler.
2. `resolve_project_path`: filesystem. Resolves symlinks and rejects any path
   whose real location is outside the project, so a symlink planted in the
   project cannot expose other files.

Workspace and run creation live in `FileStorage`; this module only answers
"is this path allowed, and where does it really point".

Stage 3 (MCP layer) reuses these functions for listFiles/readFile/writeFile and
adds role permissions on top (the Tester may only read and write test files).
"""
from __future__ import annotations

import re
from pathlib import Path

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class InvalidPathError(ValueError):
    """The path is not an allowed project-relative path."""


def validate_relative_path(path: str) -> str:
    """Return `path` unchanged if its syntax is allowed, else raise.

    The path uses "/" as separator and must name something inside the project:
    "index.html" and "src/playlist.js" are valid; "/etc/passwd", "../x",
    "a//b", "a\\b" and "C:x" are not.
    """
    if not path:
        raise InvalidPathError("The path is empty.")
    if "\0" in path:
        raise InvalidPathError("The path contains a NUL byte.")
    if "\\" in path:
        raise InvalidPathError("Use '/' as the path separator.")
    if path.startswith("/"):
        raise InvalidPathError("The path must be relative to the project.")
    if _DRIVE_PREFIX.match(path):
        raise InvalidPathError("The path must not start with a drive letter.")
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        raise InvalidPathError("The path must not contain empty, '.' or '..' segments.")
    return path


def resolve_project_path(project_root: Path, path: str) -> Path:
    """The real location of `path` inside `project_root`, or raise.

    The file does not need to exist (writers resolve new paths too). Symlinks
    are followed; if the final location is outside the project, the path is
    rejected even though its syntax is valid.
    """
    validate_relative_path(path)
    root = project_root.resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise InvalidPathError("The path points outside the project.")
    return resolved
