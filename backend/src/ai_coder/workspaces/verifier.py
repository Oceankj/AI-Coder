"""Run an optional verifier provisioned by the backend operator."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal

VERIFIER_TIMEOUT_SECONDS = 90
MAX_OUTPUT_BYTES = 64_000
MAX_RUN_FEEDBACK = 2_400
CHECK_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,63}")


class ProjectVerifierError(RuntimeError):
    """The verifier could not provide reliable evidence."""


@dataclass(frozen=True)
class ProjectVerification:
    passed: bool
    details: str
    check_ids: tuple[str, ...] = ()
    failed_check: str | None = None
    failure_code: str | None = None
    pending: str = ""


async def verify_project(
    executable: Path, project: Path, workspaces: Path, *, check: str | None = None,
) -> ProjectVerification:
    """Run a trusted executable with the project path and an optional retry check."""
    if not executable.is_absolute():
        raise ProjectVerifierError("The project verifier requires an absolute executable path.")
    try:
        command = executable.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProjectVerifierError("The configured project verifier does not exist.") from None
    if command.is_relative_to(workspaces.resolve()) or not command.is_file() or not os.access(command, os.X_OK):
        raise ProjectVerifierError("The project verifier must be executable and outside managed workspaces.")
    if check is not None and not CHECK_TOKEN.fullmatch(check):
        raise ProjectVerifierError("The project verifier retry requires a valid check ID.")
    arguments = [str(command), str(project.resolve())]
    if check is not None:
        arguments.append(check)
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments, cwd=command.parent,
            env={"PATH": os.environ.get("PATH", os.defpath)},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name == "posix",
        )
    except OSError:
        raise ProjectVerifierError("Could not start the configured project verifier.") from None
    collected = False
    try:
        async with asyncio.timeout(VERIFIER_TIMEOUT_SECONDS):
            try:
                await process.stdout.readexactly(MAX_OUTPUT_BYTES + 1)
            except asyncio.IncompleteReadError as end:
                output = end.partial
            else:
                raise ProjectVerifierError("The project verifier exceeded its report size limit.")
            status = await process.wait()
            collected = True
    except TimeoutError:
        raise ProjectVerifierError("The project verifier timed out.") from None
    finally:
        if not collected:
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.returncode is None:
                    process.kill()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.communicate(), timeout=3)
    result = _parse_report(status, output)
    if check is not None and result.check_ids[:1] != (check,):
        raise ProjectVerifierError("The project verifier did not report the requested check first.")
    return result


def _parse_report(status: int, output: bytes) -> ProjectVerification:
    invalid = ProjectVerifierError(
        "The project verifier did not return a consistent result. "
        "Expected JSON check results and exit 0 for pass or 1 for failure."
    )
    try:
        report = json.loads(output)
    except (ValueError, RecursionError):
        raise invalid from None
    if not isinstance(report, dict):
        raise invalid
    passed, checks = report.get("passed"), report.get("result")
    if not isinstance(passed, bool) or not isinstance(checks, list) or not checks:
        raise invalid

    check_ids, labels, failures, pending = [], [], [], []
    failed_check = failure_code = None
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("ok"), bool):
            raise invalid
        check_id = check.get("id")
        if check_id is not None:
            if not isinstance(check_id, str) or not CHECK_TOKEN.fullmatch(check_id) or check_id in check_ids:
                raise invalid
            check_ids.append(check_id)
        name = check.get("name")
        if not isinstance(name, str) or not name.strip():
            raise invalid
        label = " ".join(name.split())[:140]
        is_pending = check.get("pending", False)
        if not isinstance(is_pending, bool):
            raise invalid
        if is_pending:
            reason = check.get("reason")
            if not check_id or not check["ok"] or not isinstance(reason, str) or not reason.strip():
                raise invalid
            pending.append(f"{label}: {' '.join(reason.split())[:300]}")
        elif check["ok"]:
            labels.append(label)
        else:
            error = check.get("error")
            if not isinstance(error, str) or not error.strip():
                raise invalid
            failures.append(f"{label}: {' '.join(error.split())[:300]}")
            if check_id is not None:
                failed_check = check_id
                failure_code = check.get("code")
                if failure_code is not None and (
                    not isinstance(failure_code, str) or not CHECK_TOKEN.fullmatch(failure_code)
                ):
                    raise invalid
    if check_ids and (len(check_ids) != len(checks) or len(failures) > 1 or (failures and pending)):
        raise invalid
    if passed != (not failures) or status != (0 if passed else 1):
        raise invalid
    message = "; ".join(labels if passed else failures)
    return ProjectVerification(
        passed, message[:MAX_RUN_FEEDBACK], tuple(check_ids), failed_check, failure_code,
        "; ".join(pending)[:MAX_RUN_FEEDBACK],
    )
