# Author: Ching Kao
# Student ID: 85768427
"""Implement one feature against the spec, black-box tests and recorded failure."""

from pathlib import PurePosixPath

from ai_coder.models import AgentRole
from ai_coder.workspaces.permissions import is_test_file
from ai_coder.workspaces.service import InvalidPathError

MAX_CONTEXT_BYTES = 26_000
MAX_CONTEXT_FILE_BYTES = 10_000
MAX_CONTEXT_PATHS = 120
SOURCE_SUFFIXES = {".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx", ".html", ".css"}


def workspace_context(files, task):
    """Prefetch small, relevant files with the Coder's normal file permissions."""
    evidence = "\n".join((
        (task.get("execution") or {}).get("log") or "",
        (task.get("taskFeature") or {}).get("description") or "",
        task.get("reviewFeedback") or "",
    ))
    entries = files.list_files()

    def priority(entry):
        path = entry["path"]
        if path in evidence or PurePosixPath(path).name in evidence:
            return 0
        if is_test_file(path):
            return 1
        return 2 if path in {"package.json", "index.html"} else 3

    entries.sort(key=priority)
    contents = {}
    remaining = MAX_CONTEXT_BYTES
    for entry in entries[:MAX_CONTEXT_PATHS]:
        path = entry["path"]
        name = PurePosixPath(path)
        if any(part.startswith(".") for part in name.parts):
            continue
        if path != "package.json" and name.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if entry["size"] > min(remaining, MAX_CONTEXT_FILE_BYTES):
            continue
        try:
            content = files.read_file(path)
        except (OSError, InvalidPathError, ValueError):
            continue
        size = len(content.encode())
        if size <= min(remaining, MAX_CONTEXT_FILE_BYTES):
            contents[path] = content
            remaining -= size
    return {
        "paths": [entry["path"] for entry in entries[:MAX_CONTEXT_PATHS]],
        "hasMorePaths": len(entries) > MAX_CONTEXT_PATHS,
        "files": contents,
    }


async def implement(agent, task):
    await agent(
        AgentRole.CODER,
        "Coder. Implement or repair only this feature using writeFile. "
        "When repairInstruction is present, apply that specific correction, including an earlier feature if identified. "
        "Use interfaceLanguage for visible copy, accessibility labels, and the document language. "
        "An explicit user clarification about the interface language takes precedence over an older plan. "
        "Start with workspaceContext.files and the recorded failure. Read or list only missing context. "
        "When the provided context suffices, request the related writeFile calls together in one reply. "
        "Implement any systemChecks browser behavior in the rendered page, including the real file-input change "
        "handler, visible imported song names, and the linked stylesheet when listed. "
        "Create every implementation file required by the tests "
        "and the feature criteria, including the actual HTML entry point for a web app. "
        "Keep package.json's test runner and module format compatible with the existing tests. "
        "Do not add test-only application behavior or bypass failed assertions. "
        "When reviewFeedback names a project-wide acceptance defect, repair that named behavior"
        " even when it crosses the current feature boundary. Preserve unrelated features. "
        "If runChecks reports a browser failure, fix the reported website behavior even if it belongs to an earlier feature. "
        "For browser file inputs, retain each real File/Blob object by reference alongside"
        " its relative path. Read metadata from the file bytes using documented format fields;"
        " handle unsupported or absent tags with the specified fallback. Wire the rendered"
        " actions to the actual feature data. When a user generates an ordered selection,"
        " playback, saving, and export of that selection must agree on its items and order."
        " Restore saved data in a fresh page using stable identifiers, and reconnect local"
        " files after selection where the feature requires it. "
        "Each writeFile must contain the complete file, never a partial file awaiting an append. "
        "After writing all required files, finish with a brief response and "
        "no more tool calls. Preserve other features. Do not change tests.",
        task,
        stage="Coder",
        writable=True,
    )
