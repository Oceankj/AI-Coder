# Author: Shih-Yun Huang
# Student ID: 20645816
# Author: Ching Kao
# Student ID: 85768427
"""Run only supported project test runners inside Node's project permission boundary.

No package script is executed as a shell command. A package.json test script of
"jest" selects a fixed Jest CLI command; absent or "node --test" selects the
fixed Node command. Both run only *.test.js files with a minimal environment
and a timeout, and their actual results are recorded in checks.json.
"""
from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ai_coder.storage.repository import FileStorage
from ai_coder.models import CheckExecution, RunContext, format_timestamp
from ai_coder.workspaces.permissions import TEST_FILE_SUFFIX, is_test_file
from ai_coder.workspaces.verifier import verify_project

DEFAULT_TIMEOUT_SECONDS = 60.0
BROWSER_FAILURE = "[runChecks] Browser check failed: "

# The runner prints its summary last. Bound retained output from noisy tests.
MAX_OUTPUT_CHARS = 20_000
TAP_CAPTURE_MARKER = "Earlier TAP failures retained from truncated output:\n"

# What checks.json records as the command (the project path is left out).
NODE_COMMAND_LABEL = (
    "node --permission --allow-fs-read=<project> --allow-fs-write=<project> "
    f'--test --test-isolation=none --test-reporter=tap "**/*{TEST_FILE_SUFFIX}"'
)
JEST_CACHE_DIR = ".ai-coder-jest-cache"
JEST_TEMP_DIR = ".ai-coder-jest-tmp"
JEST_COMMAND_LABEL = (
    "node --permission --allow-fs-read=<project> --allow-fs-write=<project> "
    f'node_modules/jest/bin/jest.js --runInBand --no-cache --no-color '
    f'--cacheDirectory=<project>/{JEST_CACHE_DIR} --testMatch="**/*{TEST_FILE_SUFFIX}"'
)


class TestRunner(StrEnum):
    NODE = "node:test"
    JEST = "jest"


class TestRunnerError(ValueError):
    """The project declares a runner this executor cannot safely run."""


def test_runner_for_project(project: Path) -> TestRunner:
    manifest_path = project / "package.json"
    if not manifest_path.exists():
        return TestRunner.NODE
    if manifest_path.is_symlink():
        raise TestRunnerError("package.json must not be a symlink.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TestRunnerError("package.json is not readable JSON.") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("scripts", {}), dict):
        raise TestRunnerError("package.json scripts must be an object.")
    script = manifest.get("scripts", {}).get("test")
    if script is None or script == "node --test":
        return TestRunner.NODE
    if script != "jest":
        raise TestRunnerError("Unsupported package.json test script. Use 'jest' or 'node --test'.")
    cli = project / "node_modules" / "jest" / "bin" / "jest.js"
    if not cli.is_file() or not cli.resolve().is_relative_to(project.resolve()):
        raise TestRunnerError("Jest is selected but not installed in this workspace; declare and install jest.")
    return TestRunner.JEST


def test_path_failure(project: Path, log: str) -> str | None:
    """Attribute out-of-project file access to the test that requested it."""
    root = project.resolve()
    for match in re.finditer(r"Cannot find module ['\"](/[^'\"\n]+)['\"] imported from ([^\n]+)", log):
        target, source = match.groups()
        requested = Path(target).resolve()
        importer = Path(source.rstrip("\"'")).resolve()
        if importer.is_relative_to(root) and is_test_file(importer.name) and not requested.is_relative_to(root):
            test = importer.relative_to(root).as_posix()
            return f"{test} imports {os.path.relpath(requested, root)}, outside the project. Resolve the import from the test file."

    for failure in re.split(r"(?m)^not ok ", log)[1:]:
        if "ERR_ACCESS_DENIED" not in failure or "--allow-fs-read" not in failure:
            continue
        for frame in re.finditer(r"(file:///[^\n]+?):\d+:\d+\)?[\r\n]", failure):
            source = Path(unquote(urlsplit(frame.group(1)).path)).resolve()
            if not source.is_relative_to(root):
                continue
            if is_test_file(source.name):
                test = source.relative_to(root).as_posix()
                return f"{test} attempted a filesystem read outside the project. Resolve the asset from the test file."
            break
    return None


def test_setup_failure(project: Path, log: str) -> str | None:
    """Identify a missing browser global originating inside the generated test."""
    root = project.resolve()
    for failure in re.split(r"(?m)^not ok ", log)[1:]:
        missing = re.search(r"\b(URL|File|Blob|window|document|localStorage|navigator) is not defined\b", failure)
        if not missing or "ReferenceError" not in failure:
            continue
        stack = failure.partition("  stack:")[2]
        for frame in re.finditer(r"(file:///[^\n]+?):\d+:\d+\)?[\r\n]", stack):
            source = Path(unquote(urlsplit(frame.group(1)).path)).resolve()
            if not source.is_relative_to(root):
                continue
            if is_test_file(source.name):
                return (
                    f"{source.relative_to(root)} uses an unavailable {missing.group(1)} global. "
                    "Use an explicit built-in import or an isolated fixture and restore the original global after the test."
                )
            break
    return None


async def run_checks(
    storage: FileStorage,
    context: RunContext,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    browser_verifier: Path | None = None,
) -> CheckExecution:
    """Execute the suite for this run and return the persisted execution."""
    if not any(is_test_file(file.path) for file in storage.list_project_files(context)):
        raise ValueError(f"No test files (*{TEST_FILE_SUFFIX}) exist yet.")
    project = storage.project_dir(context).resolve()
    runner = test_runner_for_project(project)
    started_at = _now()
    exit_code, timed_out, output = await _run_command(project, runner, timeout_seconds)
    if exit_code not in (0, None) and "SyntaxError" in output:
        diagnostic = await _syntax_diagnostic(project, storage.list_project_files(context))
        if diagnostic:
            remaining = MAX_OUTPUT_CHARS - len(diagnostic) - 1
            if output.startswith(TAP_CAPTURE_MARKER) and len(output) > remaining:
                evidence, tail = output.split("\nRemaining TAP output:\n", 1)
                marker = "\nRemaining TAP output:\n"
                output = evidence + marker + tail[-(remaining - len(evidence) - len(marker)):]
            output = diagnostic + "\n" + output[-remaining:]
    counts = _parse_jest_counts(output) if runner == TestRunner.JEST else _parse_tap_counts(output)
    if exit_code not in (0, None) and counts["pass"] == counts["fail"] == 0:
        # A suite can fail during setup before any test is counted by Node or Jest.
        counts["fail"] = 1
    if browser_verifier is not None and exit_code == 0 and not timed_out and counts["pass"] > 0:
        verification = await verify_project(browser_verifier, project, storage.root)
        if not verification.passed:
            exit_code = 1
            counts["fail"] += 1
            output = BROWSER_FAILURE + verification.details + "\n" + output
        else:
            label = "Browser check pending: " + verification.pending if verification.pending else (
                "Browser check passed: " + verification.details
            )
            output = "[runChecks] " + label + "\n" + output
        output = output[:MAX_OUTPUT_CHARS]
    return storage.append_check_execution(
        context,
        command=JEST_COMMAND_LABEL if runner == TestRunner.JEST else NODE_COMMAND_LABEL,
        exit_code=exit_code,
        timed_out=timed_out,
        passed=counts["pass"],
        failed=counts["fail"] + counts["cancelled"],
        log=output,
        started_at=started_at,
        finished_at=_now(),
    )


async def _syntax_diagnostic(project: Path, files) -> str:
    """Attribute parser failures to tests or implementation without executing code."""
    try:
        async with asyncio.timeout(10):
            for file in files:
                path = project / file.path
                if path.suffix not in {".js", ".cjs", ".mjs"} or path.is_symlink():
                    continue
                process = await asyncio.create_subprocess_exec(
                    "node", "--permission", f"--allow-fs-read={project}", "--check", str(path),
                    cwd=project, env={"PATH": os.environ.get("PATH", "")},
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    tail = OutputTail(2000)
                    await tail.collect(process.stdout)
                    code = await process.wait()
                    if code and "SyntaxError" in tail.text():
                        owner = "test" if is_test_file(file.path) else "implementation"
                        return f"[runChecks] Syntax error in {owner} file: {file.path}\n{tail.text()}"
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
    except (TimeoutError, OSError):
        pass  # Preserve the original runner failure if attribution is unavailable.
    return ""


async def _run_command(project: Path, runner: TestRunner, timeout_seconds: float) -> tuple[int | None, bool, str]:
    """Run a fixed Node or Jest command in `project`.

    Returns (exit code, timed out, output tail). The exit code is None when
    the timeout killed the process.
    """
    command = [
        "node",
        "--permission",
        f"--allow-fs-read={project}",
        f"--allow-fs-write={project}",
    ]
    environment = {"PATH": os.environ.get("PATH", "")}
    if runner == TestRunner.JEST:
        for name in (JEST_CACHE_DIR, JEST_TEMP_DIR):
            directory = project / name
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise TestRunnerError(f"Jest temporary directory {name} must be a real directory.")
            directory.mkdir(exist_ok=True)
        environment["TMPDIR"] = str(project / JEST_TEMP_DIR)
        command.extend([
            str(project / "node_modules" / "jest" / "bin" / "jest.js"),
            "--runInBand", "--no-cache", "--no-color",
            f"--cacheDirectory={project / JEST_CACHE_DIR}",
            f"--testMatch=**/*{TEST_FILE_SUFFIX}",
        ])
    else:
        command.extend(["--test", "--test-isolation=none", "--test-reporter=tap", f"**/*{TEST_FILE_SUFFIX}"])
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=project,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # one combined log
        )
    except FileNotFoundError:
        return None, False, "Node.js ('node') was not found on PATH. Install Node.js 22.13 or later."

    tail = TapOutput(MAX_OUTPUT_CHARS) if runner == TestRunner.NODE else OutputTail(MAX_OUTPUT_CHARS)
    timed_out = False
    try:
        await asyncio.wait_for(tail.collect(process.stdout), timeout_seconds)
        exit_code = await process.wait()
    except asyncio.TimeoutError:
        timed_out = True
        exit_code = None
        tail.add(f"\n[runChecks] Stopped: the tests ran longer than {timeout_seconds:g} seconds.\n")
    finally:
        # Also runs when the agent itself is cancelled: never leave node running.
        if process.returncode is None:
            process.kill()
            await process.wait()
    return exit_code, timed_out, tail.text()


class OutputTail:
    """Keeps the last `limit` characters of a process's output."""

    def __init__(self, limit: int) -> None:
        """Start with an empty buffer that holds at most `limit` characters."""
        self.limit = limit
        self._text = ""

    def add(self, chunk: str) -> None:
        """Append `chunk`, dropping the oldest text beyond the limit."""
        self._text = (self._text + chunk)[-self.limit :]

    async def collect(self, stream: asyncio.StreamReader) -> None:
        """Read `stream` until it closes. What was read stays available on timeout."""
        while chunk := await stream.read(4096):
            self.add(chunk.decode("utf-8", errors="replace"))

    def text(self) -> str:
        """The collected output."""
        return self._text


class TapOutput(OutputTail):
    """Preserve compact early TAP evidence if verbose test output evicts it."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit)
        self._truncated = False
        self._line_prefix = ""
        self._failures: dict[str, list[str]] = {}
        self._current: list[str] | None = None
        self._error_lines = 0

    async def collect(self, stream: asyncio.StreamReader) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await stream.read(4096):
            self.add(decoder.decode(chunk))
        self.add(decoder.decode(b"", final=True))
        if self._line_prefix:
            self._capture(self._line_prefix)

    def add(self, chunk: str) -> None:
        self._truncated |= len(self._text) + len(chunk) > self.limit
        super().add(chunk)
        lines = chunk.split("\n")
        for line in lines[:-1]:
            self._capture((self._line_prefix + line)[:240])
            self._line_prefix = ""
        self._line_prefix = (self._line_prefix + lines[-1])[:240]

    def _capture(self, line: str) -> None:
        if line.startswith("not ok "):
            self._current = (self._failures.setdefault(line[:200], [])
                             if len(self._failures) < 12 else None)
            self._error_lines = 0
        elif line.startswith(("ok ", "# Subtest:", "  ...")):
            self._current = None
        elif self._current is not None and len(self._current) < 8:
            if line.startswith(("  error:", "  code:", "  failureType:", "  actual:", "  expected:", "  location:")):
                self._current.append(line)
                self._error_lines = 2 if line.startswith("  error:") and line.rstrip().endswith("|-") else 0
            elif self._error_lines and line.startswith("    ") and line.strip():
                self._current.append(line)
                self._error_lines -= 1

    def text(self) -> str:
        if not self._truncated or not self._failures:
            return super().text()
        excerpts = {
            heading: "\n".join((heading, *details))[:460] + "\n  ...\n"
            for heading, details in self._failures.items()
        }
        marker = "\nRemaining TAP output:\n"
        reserved = len(TAP_CAPTURE_MARKER) + sum(map(len, excerpts.values())) + len(marker)
        tail = self._text[-(self.limit - reserved):]
        visible = {line[:200] for line in tail.splitlines() if line.startswith("not ok ")}
        missing = "".join(excerpt for heading, excerpt in excerpts.items() if heading not in visible)
        return TAP_CAPTURE_MARKER + missing + marker + tail if missing else super().text()


_SUMMARY_LINE = re.compile(r"^# (pass|fail|cancelled) (\d+)\s*$", re.MULTILINE)


def _parse_tap_counts(output: str) -> dict[str, int]:
    """Read the "# pass/fail/cancelled N" summary lines of TAP output.

    Counts that are missing (for example, the process was killed before the
    summary) are 0; the exit code and timeout still mark such a run as failed.
    """
    counts = {"pass": 0, "fail": 0, "cancelled": 0}
    for name, value in _SUMMARY_LINE.findall(output):
        counts[name] = int(value)  # the last summary wins
    return counts


def _parse_jest_counts(output: str) -> dict[str, int]:
    """Read Jest's final Tests summary, including suites that fail before assertions."""
    summary = next((line for line in reversed(output.splitlines()) if line.startswith("Tests:")), "")
    passed = re.search(r"(\d+) passed", summary)
    failed = re.search(r"(\d+) failed", summary)
    if summary:
        return {"pass": int(passed.group(1)) if passed else 0,
                "fail": int(failed.group(1)) if failed else 0, "cancelled": 0}
    return {"pass": 0, "fail": 1 if "Test Suites:" in output else 0, "cancelled": 0}


def _now() -> str:
    """The current time in the timestamp format used by the run files."""
    return format_timestamp(datetime.now(timezone.utc))
