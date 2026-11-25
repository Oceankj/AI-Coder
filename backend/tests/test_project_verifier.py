"""Trusted project verification gates acceptance after unit tests."""

import asyncio
import json

import pytest

from ai_coder.workspaces.verifier import ProjectVerification, ProjectVerifierError, verify_project


def executable_at(path, source):
    path.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path


def test_verifier_uses_trusted_executable_and_minimal_environment(tmp_path, monkeypatch):
    project = tmp_path / "workspaces" / "My playlist"
    project.mkdir(parents=True)
    monkeypatch.setenv("UNRELATED_TEST_SECRET", "sentinel")
    executable = executable_at(
        tmp_path / "verify",
        "import json, os, pathlib, sys\n"
        "assert len(sys.argv) == 2 and pathlib.Path(sys.argv[1]).name == 'My playlist'\n"
        "assert pathlib.Path.cwd() == pathlib.Path(sys.argv[0]).parent\n"
        "assert 'UNRELATED_TEST_SECRET' not in os.environ\n"
        "print(json.dumps({'passed': True, 'result': [{'name': 'Uses local files', 'ok': True}]}))\n",
    )
    result = asyncio.run(verify_project(executable, project, project.parent))
    assert result == ProjectVerification(True, "Uses local files")

    symlink = tmp_path / "workspace-verifier"
    symlink.symlink_to(executable_at(project / "unsafe", "raise SystemExit('never launched')\n"))
    with pytest.raises(ProjectVerifierError, match="outside managed workspaces"):
        asyncio.run(verify_project(symlink, project, project.parent))


@pytest.mark.parametrize(("source", "error"), [
    ("print('{not-json')\n", "consistent result"),
    ('''print('{"passed":true,"result":[{"name":"Check","ok":true}]}')
raise SystemExit(1)
''', "consistent result"),
    ("print('a' * 65_536)\n", "report size limit"),
])
def test_verifier_rejects_invalid_or_oversize_reports(tmp_path, source, error):
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir()
    executable = executable_at(tmp_path / "verify", source)
    with pytest.raises(ProjectVerifierError, match=error):
        asyncio.run(verify_project(executable, workspaces, workspaces))


def test_verifier_hard_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_coder.workspaces.verifier.VERIFIER_TIMEOUT_SECONDS", 0.15)
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir()
    executable = executable_at(tmp_path / "verify", "import time\ntime.sleep(30)\n")
    with pytest.raises(ProjectVerifierError, match="timed out"):
        asyncio.run(verify_project(executable, workspaces, workspaces))
