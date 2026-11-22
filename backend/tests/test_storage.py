# Author: Ching Kao
# Student ID: 85768427
"""Step 2: file storage for workspaces and runs.

`FileStorage` is the only module that touches the run directory. These tests
pin the on-disk layout and JSON formats that stage 3 (MCP server) and stage 4
(agents) build on, as documented in docs/backend-spec.md.
"""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from ai_coder.models import AgentRole, PlannedFeature, RunContext, TaskFeature
from ai_coder.storage.repository import FileStorage


class FakeClock:
    """Returns a strictly increasing time so ordering tests are deterministic."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 18, 8, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def storage(tmp_path):
    return FileStorage(tmp_path / "workspaces", clock=FakeClock())


@pytest.fixture
def run(storage):
    workspace = storage.create_workspace("Demo")
    return storage.create_run(
        workspace.id, "Music Playlist Mixer", ["Pick genres", "Pick a mood"]
    )


def ctx(run) -> RunContext:
    return RunContext(workspace_id=run.workspace_id, run_id=run.id)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- Workspaces -----------------------------------------------------------


def test_create_workspace_writes_metadata(storage):
    workspace = storage.create_workspace("Demo")
    metadata = read_json(storage.root / workspace.id / "metadata.json")
    assert metadata == {
        "id": workspace.id,
        "name": "Demo",
        "createdAt": "2026-11-18T08:00:01.000Z",
    }


def test_list_workspaces_in_creation_order(storage):
    first = storage.create_workspace("First")
    second = storage.create_workspace("Second")
    assert [w.id for w in storage.list_workspaces()] == [first.id, second.id]


def test_list_workspaces_ignores_stray_directories(storage):
    storage.create_workspace("Real")
    (storage.root / "not-a-workspace").mkdir()
    assert [w.name for w in storage.list_workspaces()] == ["Real"]


def test_get_workspace(storage):
    workspace = storage.create_workspace("Demo")
    assert storage.get_workspace(workspace.id) == workspace
    assert storage.get_workspace("missing") is None


@pytest.mark.parametrize("bad_id", ["../etc", "a/b", "", ".", "x" * 65, "a\0b"])
def test_unsafe_ids_are_treated_as_missing(storage, bad_id):
    # IDs become directory names, so anything that is not a plain token must
    # never reach the filesystem.
    assert storage.get_workspace(bad_id) is None
    assert storage.get_run(bad_id, bad_id) is None
    assert storage.list_runs(bad_id) is None


# --- Runs -----------------------------------------------------------------


def test_create_run_writes_initial_files(storage, run):
    run_dir = storage.run_dir(ctx(run))
    assert read_json(run_dir / "run.json") == {
        "id": run.id,
        "workspaceId": run.workspace_id,
        "status": "queued",
        "createdAt": run.created_at,
        "activeRole": None,
        "error": None,
        "checks": {"build": "not_run", "tests": "not_run"},
        "repairCount": 0,
        "input": {
            "description": "Music Playlist Mixer",
            "requirements": ["Pick genres", "Pick a mood"],
        },
    }
    assert read_json(run_dir / "tasks.json") == {"tasks": []}
    assert read_json(run_dir / "checks.json") == {"executions": []}
    assert read_json(run_dir / "usage.json") == {
        "apiCalls": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
    }
    assert (run_dir / "project").is_dir()
    assert (run_dir / "artifacts").is_dir()


def test_create_run_records_queued_event(storage, run):
    events = storage.list_events(ctx(run))
    assert [(e.id, e.type) for e in events] == [(1, "queued")]


def test_create_run_for_missing_workspace_raises(storage):
    with pytest.raises(LookupError):
        storage.create_run("missing", "x", [])


def test_list_runs_newest_first(storage):
    workspace = storage.create_workspace("Demo")
    older = storage.create_run(workspace.id, "older", [])
    newer = storage.create_run(workspace.id, "newer", [])
    assert [r.id for r in storage.list_runs(workspace.id)] == [newer.id, older.id]


def test_list_runs_of_missing_workspace_is_none(storage):
    assert storage.list_runs("missing") is None


def test_run_from_another_workspace_is_not_found(storage, run):
    other = storage.create_workspace("Other")
    assert storage.get_run(other.id, run.id) is None
    assert storage.get_run(run.workspace_id, run.id) == run


def test_update_run_persists_changes(storage, run):
    updated = storage.update_run(
        ctx(run), status="running", active_role=AgentRole.CODER
    )
    assert updated.status == "running"
    assert updated.active_role == AgentRole.CODER
    reloaded = storage.get_run(run.workspace_id, run.id)
    assert reloaded == updated
    assert read_json(storage.run_dir(ctx(run)) / "run.json")["activeRole"] == "coder"


def test_update_run_rejects_unknown_fields(storage, run):
    with pytest.raises(ValueError):
        storage.update_run(ctx(run), not_a_field=1)


def test_writes_leave_no_temporary_files(storage, run):
    storage.update_run(ctx(run), status="running")
    leftovers = [p.name for p in storage.run_dir(ctx(run)).iterdir() if ".tmp" in p.name]
    assert leftovers == []


# --- Events ---------------------------------------------------------------


def test_append_event_increments_ids(storage, run):
    second = storage.append_event(ctx(run), "role_started", "Planner started.")
    third = storage.append_event(ctx(run), "role_finished", "Planner finished.")
    assert (second.id, third.id) == (2, 3)
    line = (storage.run_dir(ctx(run)) / "events.jsonl").read_text().splitlines()[1]
    assert json.loads(line) == {
        "id": 2,
        "type": "role_started",
        "message": "Planner started.",
        "createdAt": second.created_at,
    }


def test_append_event_records_agent_role_without_changing_system_events(storage, run):
    agent = storage.append_event(ctx(run), "tool_call", "coder → writeFile", role=AgentRole.CODER)
    runner = storage.append_event(ctx(run), "checks", "Tests passed.")
    events = storage.list_events(ctx(run))
    assert agent.role == AgentRole.CODER
    assert events[-2].to_json()["role"] == "coder"
    assert runner.role is None
    assert "role" not in events[-1].to_json()


def test_list_events_after_cursor(storage, run):
    storage.append_event(ctx(run), "a", "one")
    storage.append_event(ctx(run), "b", "two")
    assert [e.id for e in storage.list_events(ctx(run), after=1)] == [2, 3]
    assert storage.list_events(ctx(run), after=3) == []


def test_concurrent_event_appends_get_unique_ids(storage, run):
    threads = [
        threading.Thread(target=storage.append_event, args=(ctx(run), "t", str(i)))
        for i in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = [e.id for e in storage.list_events(ctx(run))]
    assert ids == list(range(1, 22))


# --- Usage ----------------------------------------------------------------


def test_add_usage_accumulates(storage, run):
    storage.add_usage(ctx(run), input_tokens=100, output_tokens=20)
    usage = storage.add_usage(
        ctx(run), input_tokens=50, output_tokens=5, total_tokens=70
    )
    # total_tokens defaults to input + output, but providers may report more
    # (for example Gemini thinking tokens), so an explicit total wins.
    assert usage.model_dump() == {
        "api_calls": 2,
        "input_tokens": 150,
        "output_tokens": 25,
        "total_tokens": 190,
    }
    assert storage.get_usage(ctx(run)) == usage


def test_add_usage_rejects_negative_numbers(storage, run):
    with pytest.raises(ValueError):
        storage.add_usage(ctx(run), input_tokens=-1, output_tokens=0)


# --- Tasks (handoffs between agents) ----------------------------------------


def test_publish_task_copies_run_input(storage, run):
    task = storage.publish_task(ctx(run), AgentRole.PLANNER, "Write a plan.")
    assert task.id == "planner-1"
    assert task.sequence == 1
    assert task.status == "pending"
    assert task.description == "Music Playlist Mixer"
    assert task.requirements == ["Pick genres", "Pick a mood"]
    assert task.plan is None
    assert task.feature is None
    assert task.repair is False
    assert task.result is None
    on_disk = read_json(storage.run_dir(ctx(run)) / "tasks.json")["tasks"][0]
    assert on_disk["id"] == "planner-1"
    assert on_disk["previousFailure"] is None


def test_feature_tasks_carry_the_feature(storage, run):
    feature = TaskFeature(number=2, total=3, title="Pick a mood", description="Mood filter")
    task = storage.publish_task(
        ctx(run), AgentRole.CODER, "Implement it.", plan="p", feature=feature
    )
    assert task.feature == feature
    on_disk = read_json(storage.run_dir(ctx(run)) / "tasks.json")["tasks"][0]
    assert on_disk["feature"] == {
        "number": 2,
        "total": 3,
        "title": "Pick a mood",
        "description": "Mood filter",
    }


def test_repeated_tasks_get_new_sequence_numbers(storage, run):
    storage.publish_task(ctx(run), AgentRole.CODER, "Write code.", plan="p")
    second = storage.publish_task(
        ctx(run),
        AgentRole.CODER,
        "Fix code.",
        plan="p",
        repair=True,
        previous_failure="1 failed",
    )
    assert (second.id, second.sequence, second.repair) == ("coder-2", 2, True)
    assert storage.get_current_task(ctx(run), AgentRole.CODER) == second
    assert storage.get_current_task(ctx(run), AgentRole.TESTER) is None


def test_submit_result_marks_task_submitted(storage, run):
    storage.publish_task(ctx(run), AgentRole.PLANNER, "Write a plan.")
    task = storage.submit_result(
        ctx(run),
        AgentRole.PLANNER,
        summary="The plan",
        artifact_paths=[],
        outcome="success",
    )
    assert task.status == "submitted"
    assert task.result.summary == "The plan"
    assert task.result.outcome == "success"
    assert task.result.features == []
    assert storage.get_current_task(ctx(run), AgentRole.PLANNER) == task


def test_planner_result_can_list_features(storage, run):
    storage.publish_task(ctx(run), AgentRole.PLANNER, "Write a plan.")
    task = storage.submit_result(
        ctx(run),
        AgentRole.PLANNER,
        summary="The plan",
        artifact_paths=[],
        outcome="success",
        features=[
            {"title": "Pick genres", "description": "Filter songs by genre"},
            PlannedFeature(title="Pick a mood", description="Filter by energy"),
        ],
    )
    assert [f.title for f in task.result.features] == ["Pick genres", "Pick a mood"]
    on_disk = read_json(storage.run_dir(ctx(run)) / "tasks.json")["tasks"][0]
    assert on_disk["result"]["features"][0] == {
        "title": "Pick genres",
        "description": "Filter songs by genre",
    }


def test_submit_result_without_task_raises(storage, run):
    with pytest.raises(LookupError):
        storage.submit_result(
            ctx(run), AgentRole.TESTER, summary="x", artifact_paths=[], outcome="success"
        )


# --- Check executions -------------------------------------------------------


def test_append_check_execution_derives_outcome(storage, run):
    passed = storage.append_check_execution(
        ctx(run), command="node --test", exit_code=0, timed_out=False,
        passed=3, failed=0, log="ok",
    )
    failed = storage.append_check_execution(
        ctx(run), command="node --test", exit_code=1, timed_out=False,
        passed=2, failed=1, log="not ok",
    )
    timed_out = storage.append_check_execution(
        ctx(run), command="node --test", exit_code=None, timed_out=True,
        passed=0, failed=0, log="",
    )
    assert [e.id for e in (passed, failed, timed_out)] == [1, 2, 3]
    assert [e.outcome for e in (passed, failed, timed_out)] == [
        "passed",
        "failed",
        "failed",
    ]
    assert storage.list_check_executions(ctx(run)) == [passed, failed, timed_out]


def test_check_log_is_bounded(storage, run):
    execution = storage.append_check_execution(
        ctx(run), command="node --test", exit_code=1, timed_out=False,
        passed=0, failed=1, log="x" * 50_000 + "END",
    )
    # Keep the end of the log: test runners print the failure summary last.
    assert len(execution.log) <= 20_000
    assert execution.log.endswith("END")


# --- Startup recovery -------------------------------------------------------


def test_fail_interrupted_runs(storage):
    workspace = storage.create_workspace("Demo")
    queued = storage.create_run(workspace.id, "queued", [])
    running = storage.create_run(workspace.id, "running", [])
    done = storage.create_run(workspace.id, "done", [])
    storage.update_run(ctx(running), status="running", active_role=AgentRole.CODER)
    storage.update_run(ctx(done), status="completed")

    recovered = storage.fail_interrupted_runs()

    assert {c.run_id for c in recovered} == {queued.id, running.id}
    for run_id in (queued.id, running.id):
        run = storage.get_run(workspace.id, run_id)
        assert run.status == "failed"
        assert run.active_role is None
        assert "restarted" in run.error
        assert storage.list_events(RunContext(workspace.id, run_id))[-1].type == "failed"
    assert storage.get_run(workspace.id, done.id).status == "completed"


# --- Ordering when the clock does not move -------------------------------------------


class FrozenClock:
    """Always returns the same time, like two requests in the same millisecond."""

    def __call__(self) -> datetime:
        return datetime(2026, 11, 18, 8, 0, 0, tzinfo=timezone.utc)


def test_timestamps_are_strictly_increasing_even_if_the_clock_stalls(tmp_path):
    storage = FileStorage(tmp_path / "workspaces", clock=FrozenClock())
    first = storage.create_workspace("First")
    second = storage.create_workspace("Second")
    assert second.created_at > first.created_at
    assert [w.name for w in storage.list_workspaces()] == ["First", "Second"]


def test_runs_created_in_the_same_millisecond_keep_their_order(tmp_path):
    storage = FileStorage(tmp_path / "workspaces", clock=FrozenClock())
    workspace = storage.create_workspace("Demo")
    older = storage.create_run(workspace.id, "older", [])
    newer = storage.create_run(workspace.id, "newer", [])
    assert [r.id for r in storage.list_runs(workspace.id)] == [newer.id, older.id]
