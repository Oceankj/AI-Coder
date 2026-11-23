# Author: Shih-Yun Huang
# Student ID: 20645816
"""Stage 3, step 1: role permissions for the MCP file tools.

Checks the table in ai_coder/workspaces/permissions.py: who may read and
write which project files, and that symlinks cannot get around the rules.
"""
import os

import pytest

from ai_coder.models import AgentRole
from ai_coder.workspaces.permissions import (
    PermissionDeniedError,
    authorize_read,
    authorize_write,
    can_read,
    can_write,
    is_test_file,
)
from ai_coder.workspaces.service import InvalidPathError

PLANNER, CODER, TESTER = AgentRole.PLANNER, AgentRole.CODER, AgentRole.TESTER


@pytest.mark.parametrize(
    "path, expected",
    [
        ("mix.test.js", True),
        ("tests/mix.test.js", True),
        ("mix.TEST.js", True),  # case does not matter
        ("playlist.js", False),
        ("index.html", False),
        ("package.json", False),
        ("test.js", False),  # no ".test.js" suffix
        ("mix.test.js.bak", False),
    ],
)
def test_is_test_file(path, expected):
    """Only names ending in .test.js count as tests."""
    assert is_test_file(path) is expected


@pytest.mark.parametrize(
    "role, path, read, write",
    [
        (PLANNER, "playlist.js", True, False),
        (PLANNER, "mix.test.js", True, False),
        (CODER, "playlist.js", True, True),
        (CODER, "index.html", True, True),
        (CODER, "package.json", True, True),
        (CODER, "mix.test.js", True, False),  # tests are the spec
        (TESTER, "mix.test.js", True, True),
        (TESTER, "playlist.js", False, False),  # black-box testing
        (TESTER, "package.json", True, False),
    ],
)
def test_role_table(role, path, read, write):
    """can_read and can_write follow the table in the module docstring."""
    assert can_read(role, path) is read
    assert can_write(role, path) is write


def test_authorize_returns_real_location(tmp_path):
    """An allowed path resolves to the file inside the project."""
    assert authorize_write(CODER, tmp_path, "src/playlist.js") == tmp_path.resolve() / "src/playlist.js"
    assert authorize_read(TESTER, tmp_path, "mix.test.js") == tmp_path.resolve() / "mix.test.js"
    assert authorize_read(TESTER, tmp_path, "package.json") == tmp_path.resolve() / "package.json"


def test_denied_message_tells_the_model_what_is_allowed(tmp_path):
    """The refusal is readable and explains the rule, so the LLM can recover."""
    with pytest.raises(PermissionDeniedError, match=r"tester may not read 'playlist.js'.*only test files"):
        authorize_read(TESTER, tmp_path, "playlist.js")
    with pytest.raises(PermissionDeniedError, match=r"fix the application code"):
        authorize_write(CODER, tmp_path, "mix.test.js")
    with pytest.raises(PermissionDeniedError, match=r"Planner does not write files"):
        authorize_write(PLANNER, tmp_path, "plan.md")


@pytest.mark.parametrize("path", ["../secret.test.js", "/etc/passwd", "a/../b.test.js"])
def test_path_rules_still_apply(tmp_path, path):
    """Role checks come on top of the path checks, not instead of them."""
    with pytest.raises(InvalidPathError):
        authorize_read(PLANNER, tmp_path, path)


def test_symlink_named_like_a_test_cannot_expose_source(tmp_path):
    """A test-looking symlink to playlist.js must not let the Tester read it."""
    (tmp_path / "playlist.js").write_text("secret implementation")
    os.symlink(tmp_path / "playlist.js", tmp_path / "peek.test.js")
    with pytest.raises(PermissionDeniedError):
        authorize_read(TESTER, tmp_path, "peek.test.js")
    with pytest.raises(PermissionDeniedError):
        authorize_write(TESTER, tmp_path, "peek.test.js")
