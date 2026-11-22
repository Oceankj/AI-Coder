# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""File tools: listFiles, readFile, and writeFile.

Every path is relative to the run's project/ folder. Two layers of checks run
before any file is touched:

1. Path rules (workspaces/service.py): no absolute paths, no "..", no symlink
   that leads outside the project.
2. Role rules (workspaces/permissions.py): the Tester only touches test files,
   the Coder never edits tests, the Planner writes nothing.

Errors are raised with readable messages; the MCP server returns them to the
model as tool errors so it can correct the next call.
"""
from __future__ import annotations

from typing import Any

from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.workspaces.permissions import authorize_read, authorize_write
from ai_coder.workspaces.service import validate_relative_path

# Limits keep one tool call from flooding the model's context (and the token
# count) or filling the disk. Generated files are far smaller than this.
MAX_FILE_BYTES = 200_000


class FileTools:
    """listFiles, readFile, and writeFile for the role bound in `scope`."""

    def __init__(self, scope: ToolScope) -> None:
        """Bind the tools to one run and role."""
        self.scope = scope

    def list_files(self, directory: str = ".") -> list[dict[str, Any]]:
        """List files under `directory` ("." for the whole project).

        Returns [{"path": ..., "size": ...}] sorted by path. Every role may list
        names; reading contents is what the role rules restrict.
        """
        files = self.scope.storage.list_project_files(self.scope.context)
        if directory not in (".", ""):
            prefix = validate_relative_path(directory.rstrip("/")) + "/"
            files = [file for file in files if file.path.startswith(prefix)]
        return [{"path": file.path, "size": file.size} for file in files]

    def read_file(self, path: str) -> str:
        """Return the text content of the project file at `path`."""
        location = authorize_read(self.scope.role, self.scope.project_dir, path)
        if not location.is_file():
            raise FileNotFoundError(f"'{path}' does not exist. Call listFiles to see the project files.")
        if location.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"'{path}' is larger than {MAX_FILE_BYTES} bytes and cannot be read.")
        try:
            return location.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"'{path}' is not a UTF-8 text file.") from None

    def write_file(self, path: str, content: str) -> str:
        """Create or replace the project file at `path` with `content`.

        Missing parent folders are created. Returns a short confirmation with
        the number of bytes written.
        """
        location = authorize_write(self.scope.role, self.scope.project_dir, path)
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"The content is larger than {MAX_FILE_BYTES} bytes; split it into smaller files.")
        if location.is_dir():
            raise IsADirectoryError(f"'{path}' is a folder, not a file.")
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(data)
        return f"Wrote {path} ({len(data)} bytes)."
