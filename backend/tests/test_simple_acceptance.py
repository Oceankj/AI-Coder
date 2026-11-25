"""Final acceptance uses the latest recorded test execution."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_coder.agents.coordinator import RepairDiagnosis
from ai_coder.models import RunContext
from ai_coder.orchestration import tdd
from ai_coder.workspaces.verifier import ProjectVerifierError, verify_project


@pytest.mark.parametrize(("outcome", "passed", "accepted"), [
    ("passed", 26, True), ("failed", 25, False), ("passed", 0, False), (None, 0, False),
])
def test_final_acceptance_uses_only_latest_recorded_check(outcome, passed, accepted):
    storage = Mock()
    storage.get_run.return_value = SimpleNamespace(provider="groq")
    first = SimpleNamespace(id=1, outcome="passed", passed=26)
    latest = SimpleNamespace(id=2, outcome=outcome, passed=passed)
    storage.list_check_executions.return_value = [first, latest] if outcome else []
    workflow = tdd.TDDRun(storage, None, SimpleNamespace(project_verifier="/unused"), RunContext("ws", "run"))
    checkpoint = {"browser_check_to_retry": "local-mood"}

    if accepted:
        assert asyncio.run(workflow.acceptance(checkpoint)) == {"route": "advance"}
        assert "execution 2" in storage.append_event.call_args.args[2]
    else:
        with pytest.raises(tdd.WorkflowBlock, match="passing runChecks"):
            asyncio.run(workflow.acceptance(checkpoint))
        storage.append_event.assert_not_called()


def verifier(tmp_path, result, stage=None):
    executable = tmp_path / "checker"
    args = "assert len(sys.argv) == 2" if stage is None else f"assert sys.argv[2:] == [{stage!r}]"
    executable.write_text(
        "#!/usr/bin/env python3\nimport sys\n" + args + "\n"
        + f"print({json.dumps(result)!r})\nraise SystemExit({int(not result['passed'])})\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


def test_verifier_passes_only_the_requested_check_to_a_targeted_retry(tmp_path):
    workspaces = tmp_path / "workspaces"
    project = workspaces / "project"
    project.mkdir(parents=True)
    executable = verifier(tmp_path, {
        "passed": True,
        "result": [{"id": "local-mood", "name": "Suggest a mood", "ok": True}],
    }, stage="local-mood")

    result = asyncio.run(verify_project(executable, project, workspaces, check="local-mood"))

    assert result.passed
    assert result.check_ids == ("local-mood",)


def test_verifier_rejects_a_passing_report_for_the_wrong_retry(tmp_path):
    workspaces = tmp_path / "workspaces"
    project = workspaces / "project"
    project.mkdir(parents=True)
    executable = verifier(tmp_path, {
        "passed": True,
        "result": [{"id": "startup", "name": "Open app", "ok": True}],
    }, stage="local-mood")

    with pytest.raises(ProjectVerifierError):
        asyncio.run(verify_project(executable, project, workspaces, check="local-mood"))


@pytest.mark.parametrize(("instruction", "route"), [
    ("Accept equivalent wording and preserve the stylesheet assertion.", "tests"),
    ("Repeat the old advice.", "pause"),
])
def test_coordinator_routes_repeated_failure_and_blocks_duplicate_instruction(instruction, route, tmp_path):
    storage = Mock()
    storage.get_run.return_value = SimpleNamespace(provider="codex", repair_count=0)
    storage.project_dir.return_value = tmp_path
    workflow = tdd.TDDRun(storage, None, SimpleNamespace(max_repairs=8), RunContext("ws", "run"))
    workflow.coordinator_repair = AsyncMock(return_value=RepairDiagnosis(
        target="tester", reason="The test assumes exact wording.", instruction=instruction,
    ))
    state = {
        "spec": "Explain how to select a folder.",
        "execution": {"id": 4, "outcome": "failed", "failed": 1, "timedOut": False,
                      "log": "not ok 9 - folder instructions\n  duration_ms: 10"},
        "repair_signature": tdd.failure_signature("not ok 8 - folder instructions\n  duration_ms: 3"),
        "repair_execution": 3,
        "repair_history": ["Repeat the old advice."],
    }
    result = asyncio.run(workflow.assess(state, "Green"))
    workflow.coordinator_repair.assert_awaited_once_with(state, ["Repeat the old advice."])
    assert result["route"] == route
    assert result["repair_instruction"] == (instruction if route == "tests" else "")
    assert result["assessment"]["decision"] == ("test_invalid" if route == "tests" else "blocked")
    assert storage.update_run.call_count == int(route == "tests")
