# Author: Ching Kao
# Student ID: 85768427
"""Workspace-local dependency preparation and package validation."""

import asyncio
import json
from pathlib import Path

import pytest

from ai_coder.workspaces.environment import EnvironmentError, prepare_environment


def test_workspace_dependencies_install_once_and_reinstall_on_manifest_change(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" >> setup-calls.txt\n"
        "if [ \"$1\" = install ]; then printf '{}\\n' > package-lock.json; "
        "else mkdir -p node_modules; fi\n"
    )
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + ":/usr/bin:/bin")

    first = asyncio.run(prepare_environment(project, {"jsdom": "^26.1.0"}))
    assert first == "Workspace npm dependencies installed."
    assert json.loads((project / "package.json").read_text())["dependencies"] == {"jsdom": "^26.1.0"}
    assert (project / "node_modules").is_dir()
    assert (project / "setup-calls.txt").read_text().splitlines() == ["install", "ci"]
    assert asyncio.run(prepare_environment(project, {})) == "Workspace npm dependencies are ready."
    assert (project / "setup-calls.txt").read_text().splitlines() == ["install", "ci"]

    manifest = json.loads((project / "package.json").read_text())
    manifest["dependencies"]["jsdom"] = "^27.0.0"
    (project / "package.json").write_text(json.dumps(manifest))
    asyncio.run(prepare_environment(project, {}))
    assert (project / "setup-calls.txt").read_text().splitlines() == ["install", "ci", "install", "ci"]


@pytest.mark.parametrize("package,version", [("bad/name", "1.0.0"), ("jsdom", "file:../shared"), ("jsdom", "https://example.com/pkg")])
def test_environment_rejects_non_registry_dependencies(tmp_path: Path, package, version):
    with pytest.raises(EnvironmentError, match="Unsupported npm dependency"):
        asyncio.run(prepare_environment(tmp_path, {package: version}))
