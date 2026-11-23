# Author: Ching Kao
# Student ID: 85768427
"""Prepare npm dependencies in one workspace without running package scripts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

from ai_coder.config import DEFAULT_SETUP_TIMEOUT_SECONDS
from ai_coder.workspaces.checks import OutputTail

PACKAGE_NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
REGISTRY_VERSION = re.compile(r"^[~^]?\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?$")
NPM_ERROR_CODE = re.compile(r"(?:npm error code|npm ERR! code) ([A-Z][A-Z0-9_]+)")
MISSING_PACKAGE = re.compile(r"Cannot find (?:module|package) ['\"]([^'\"]+)['\"]")
INSTALL_MARKER = ".ai-coder-install.json"
ENVIRONMENT_MARKER = ".ai-coder-environment.json"
ENVIRONMENT_MARKER_VERSION = 1


class EnvironmentError(Exception):
    """A safe diagnostic that can be shown in a run without exposing npm output."""


def missing_npm_package(check_log: str) -> str | None:
    """Recognize only missing bare package imports, not missing project files."""
    for name in MISSING_PACKAGE.findall(check_log):
        if PACKAGE_NAME.fullmatch(name):
            return name
    return None


def environment_initialized(project: Path) -> bool:
    """Whether this workspace completed an Architect-approved setup before."""
    marker = project / ENVIRONMENT_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        return json.loads(marker.read_text()) == {"version": ENVIRONMENT_MARKER_VERSION}
    except (OSError, json.JSONDecodeError):
        return False


def mark_environment_initialized(project: Path) -> None:
    marker = project / ENVIRONMENT_MARKER
    if marker.is_symlink():
        raise EnvironmentError("Cannot mark a symlinked environment marker as ready.")
    marker.write_text(json.dumps({"version": ENVIRONMENT_MARKER_VERSION}) + "\n")


async def prepare_environment(project: Path, packages: dict[str, str], *, timeout_seconds: float = DEFAULT_SETUP_TIMEOUT_SECONDS) -> str:
    """Merge the Architect's registry dependencies and install when the manifest changed."""
    manifest_path = project / "package.json"
    for name in ("package.json", "package-lock.json", "node_modules", ".npm-home", ".npm-cache", INSTALL_MARKER):
        if (project / name).is_symlink():
            raise EnvironmentError(f"Cannot prepare an environment with a symlinked {name}.")
    if packages:
        for name, version in packages.items():
            if not PACKAGE_NAME.fullmatch(name) or not REGISTRY_VERSION.fullmatch(version):
                raise EnvironmentError(f"Unsupported npm dependency {name!r}; use a registry package with a semver version.")
        try:
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
                "name": "ai-coder-workspace", "version": "1.0.0", "private": True
            }
        except (OSError, json.JSONDecodeError) as error:
            raise EnvironmentError("package.json is not readable JSON.") from error
        if not isinstance(manifest, dict) or not isinstance(manifest.get("dependencies", {}), dict):
            raise EnvironmentError("package.json must be a JSON object with an object-valued dependencies field.")
        dependencies = dict(manifest.get("dependencies", {}))
        dependencies.update(packages)
        if dependencies != manifest.get("dependencies", {}):
            manifest["dependencies"] = dependencies
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    if not manifest_path.exists():
        return "No npm dependencies required."
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise EnvironmentError("package.json is not readable JSON.") from error
    if not isinstance(manifest, dict):
        raise EnvironmentError("package.json must be a JSON object.")
    if "workspaces" in manifest or "overrides" in manifest:
        raise EnvironmentError("Workspace package.json cannot use npm workspaces or overrides.")
    if any(manifest.get(field) for field in ("optionalDependencies", "peerDependencies", "bundledDependencies")):
        raise EnvironmentError("Workspace package.json supports dependencies and devDependencies only.")
    regular = manifest.get("dependencies", {})
    development = manifest.get("devDependencies", {})
    if not isinstance(regular, dict) or not isinstance(development, dict):
        raise EnvironmentError("package.json dependency fields must be JSON objects.")
    dependencies = {**regular, **development}
    if not dependencies:
        return "No npm dependencies required."
    for name, version in dependencies.items():
        if not isinstance(name, str) or not isinstance(version, str) or not PACKAGE_NAME.fullmatch(name) or not REGISTRY_VERSION.fullmatch(version):
            raise EnvironmentError("package.json contains an unsupported dependency; use registry packages with semver versions.")

    lock_path = project / "package-lock.json"
    def fingerprint() -> str:
        digest = hashlib.sha256(manifest_path.read_bytes())
        if lock_path.is_file():
            digest.update(lock_path.read_bytes())
        return digest.hexdigest()

    marker = project / INSTALL_MARKER
    if marker.is_file() and (project / "node_modules").is_dir():
        try:
            installed = all(
                (project / "node_modules" / name).exists() for name in dependencies
            )
            if installed and json.loads(marker.read_text()).get("manifestSha256") == fingerprint():
                return "Workspace npm dependencies are ready."
        except (OSError, json.JSONDecodeError):
            pass

    (project / ".npm-home").mkdir(exist_ok=True)
    (project / ".npm-cache").mkdir(exist_ok=True)
    user_config = project / ".npm-home" / "user.npmrc"
    global_config = project / ".npm-home" / "global.npmrc"
    for config in (user_config, global_config):
        if config.is_symlink():
            raise EnvironmentError(f"Cannot use a symlinked npm config file: {config.name}.")
        config.touch(exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(project / ".npm-home"),
        "npm_config_cache": str(project / ".npm-cache"),
        "npm_config_userconfig": str(user_config),
        "npm_config_globalconfig": str(global_config),
    }
    for command in (
        ("install", "--package-lock-only"),
        ("ci",),
    ):
        args = ("npm", *command, "--ignore-scripts", "--no-audit", "--no-fund", "--no-progress")
        try:
            process = await asyncio.create_subprocess_exec(
                *args, cwd=project, env=environment,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as error:
            raise EnvironmentError("npm was not found on PATH; install Node.js and npm on the backend host.") from error
        output = OutputTail(2000)
        try:
            await asyncio.wait_for(output.collect(process.stdout), timeout_seconds)
            code = await process.wait()
        except asyncio.TimeoutError as error:
            raise EnvironmentError(f"npm {command[0]} exceeded the environment setup timeout.") from error
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if code:
            if "Exit prior to config file resolving" in output.text():
                raise EnvironmentError(f"npm {command[0]} failed (exit {code}); npm configuration could not load.")
            match = NPM_ERROR_CODE.search(output.text())
            reason = f", {match.group(1)}" if match else ""
            raise EnvironmentError(f"npm {command[0]} failed (exit {code}{reason}); check dependency versions and registry access.")
    marker.write_text(json.dumps({"manifestSha256": fingerprint()}) + "\n")
    return "Workspace npm dependencies installed."
