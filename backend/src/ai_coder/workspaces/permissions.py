# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""Role permissions for the MCP file tools (readFile, writeFile).

The path rules in `service.py` answer "is this path inside the project?".
This module adds the second question: "may this agent role touch it?".

| Role    | Read                   | Write                                  |
| ------- | ---------------------- | -------------------------------------- |
| Planner | any project file       | nothing (it only plans)                |
| Coder   | any project file       | application files only, never tests    |
| Tester  | test files only        | test files only                        |

A test file is any file whose name ends in `.test.js` (the pattern
`node --test` runs). Why these rules:

- The Tester tests black-box: it writes tests from the requirements and the
  plan, not from the implementation, so it may not read application source.
- Tests are the specification: during a repair the Coder must fix the code,
  so it may not edit tests to make them pass.

Listing file names (listFiles) is allowed for every role; the Tester needs the
names to import the module under test. These checks are for file contents.

Error messages are read by the LLM, so they say what is allowed instead of
only "denied", which lets the model correct its next call.
"""
from __future__ import annotations

from pathlib import Path

from ai_coder.models import AgentRole
from ai_coder.workspaces.service import resolve_project_path

TEST_FILE_SUFFIX = ".test.js"


class PermissionDeniedError(PermissionError):
    """The agent's role may not read or write this file."""


def is_test_file(path: str) -> bool:
    """Return True if `path` names a test file (ends in `.test.js`).

    The check ignores case, so a Coder cannot slip a test past the rule with a
    name like "mix.TEST.js" on a case-insensitive file system (macOS).
    """
    return path.lower().endswith(TEST_FILE_SUFFIX)


def can_read(role: AgentRole, path: str) -> bool:
    """Return True if `role` may read the file at project-relative `path`."""
    if role is AgentRole.TESTER:
        return is_test_file(path)
    return True  # Planner and Coder may read every project file.


def can_write(role: AgentRole, path: str) -> bool:
    """Return True if `role` may create or overwrite the file at `path`."""
    if role is AgentRole.CODER:
        return not is_test_file(path)
    if role is AgentRole.TESTER:
        return is_test_file(path)
    return False  # The Planner writes no files.


def authorize_read(role: AgentRole, project_root: Path, path: str) -> Path:
    """Check that `role` may read `path`, and return its real location.

    Raises `InvalidPathError` (from service.py) if the path is malformed or
    leaves the project, and `PermissionDeniedError` if the role may not read it.
    """
    return _authorize(role, project_root, path, can_read, "read")


def authorize_write(role: AgentRole, project_root: Path, path: str) -> Path:
    """Check that `role` may write `path`, and return its real location.

    Raises `InvalidPathError` (from service.py) if the path is malformed or
    leaves the project, and `PermissionDeniedError` if the role may not write it.
    """
    return _authorize(role, project_root, path, can_write, "write")


def _authorize(role, project_root: Path, path: str, allowed, action: str) -> Path:
    """Shared body of authorize_read and authorize_write.

    The rule is checked twice: on the name the agent asked for, and on the
    file's real location after symlinks are followed. Otherwise a symlink named
    "peek.test.js" that points to "playlist.js" would let the Tester read
    application source.
    """
    resolved = resolve_project_path(project_root, path)
    real_relative = resolved.relative_to(project_root.resolve()).as_posix()
    if not (allowed(role, path) and allowed(role, real_relative)):
        raise PermissionDeniedError(_denied_message(role, action, path))
    return resolved


def _denied_message(role: AgentRole, action: str, path: str) -> str:
    """Build a readable refusal that also tells the model what it may do."""
    what_is_allowed = {
        (AgentRole.TESTER, "read"): f"The Tester may read only test files (*{TEST_FILE_SUFFIX}).",
        (AgentRole.TESTER, "write"): f"The Tester may write only test files (*{TEST_FILE_SUFFIX}).",
        (AgentRole.CODER, "write"): "The Coder may not change test files; fix the application code instead.",
        (AgentRole.PLANNER, "write"): "The Planner does not write files.",
    }
    hint = what_is_allowed.get((role, action), "")
    return f"The {role.value} may not {action} '{path}'. {hint}".strip()
