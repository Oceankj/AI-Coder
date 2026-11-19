"""Step 4: orchestrator and scheduler.

The orchestrator is tested with scripted agents that do exactly what each test
needs (submit or not, record passing or failing checks, raise). This pins the
rules from docs/architecture.md and docs/interfaces.md:

- Planner -> Coder -> Tester, then at most `max_repairs` Coder -> Tester rounds.
- Whether tests passed comes from checks.json (real executions), never from
  the agent's own `outcome`.
- Every failure ends the run as "failed" with a readable error, and
  activeRole is always cleared at the end.
"""
import asyncio

import pytest

from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.orchestrator import Orchestrator
from ai_coder.orchestration.recorder import RunRecorder
from ai_coder.orchestration.scheduler import RunScheduler
from ai_coder.storage.repository import FileStorage

PLANNER, CODER, TESTER = AgentRole.PLANNER, AgentRole.CODER, AgentRole.TESTER


@pytest.fixture
def storage(tmp_path):
    return FileStorage(tmp_path / "workspaces")


@pytest.fixture
def context(storage):
    workspace = storage.create_workspace("Demo")
    run = storage.create_run(workspace.id, "Playlist Mixer", ["Pick a mood"])
    return RunContext(workspace.id, run.id)


class ScriptedAgent:
    """An agent whose behavior is a plain function supplied by the test."""

    def __init__(self, role, storage, script):
        self.role = role
        self.storage = storage
        self.script = script
        self.calls = 0

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        self.calls += 1
        await self.script(self, context, recorder)


def submit(agent, context, summary="done", outcome="success"):
    agent.storage.submit_result(
        context, agent.role, summary=summary, artifact_paths=[], outcome=outcome
    )


def record_check(agent, context, *, passed: bool, log="test log"):
    agent.storage.append_check_execution(
        context,
        command="node --test",
        exit_code=0 if passed else 1,
        timed_out=False,
        passed=3 if passed else 2,
        failed=0 if passed else 1,
        log=log,
    )


async def plan(agent, context, recorder):
    submit(agent, context, summary="THE PLAN")


async def code(agent, context, recorder):
    submit(agent, context, summary="wrote code")


def scripted_tester(*results: bool):
    """A Tester that records the given check results, one per attempt."""

    async def test(agent, context, recorder):
        record_check(agent, context, passed=results[agent.calls - 1], log=f"log {agent.calls}")
        submit(agent, context, summary="ran tests")

    return test


async def passing_tester(agent, context, recorder):
    record_check(agent, context, passed=True)
    submit(agent, context, summary="ran tests")


def make_agents(storage, planner=plan, coder=code, tester=passing_tester):
    return {
        PLANNER: ScriptedAgent(PLANNER, storage, planner),
        CODER: ScriptedAgent(CODER, storage, coder),
        TESTER: ScriptedAgent(TESTER, storage, tester),
    }


def run_orchestrator(storage, context, agents, max_repairs=2):
    asyncio.run(Orchestrator(storage, agents, max_repairs=max_repairs).run(context))
    return storage.get_run(context.workspace_id, context.run_id)


def event_types(storage, context):
    return [event.type for event in storage.list_events(context)]


# --- Successful runs ---------------------------------------------------------------


def test_successful_run_completes(storage, context):
    run = run_orchestrator(storage, context, make_agents(storage))
    assert run.status == "completed"
    assert run.active_role is None
    assert run.error is None
    assert run.checks.tests == "passed"
    assert run.checks.build == "not_run"
    assert run.repair_count == 0


def test_successful_run_events(storage, context):
    run_orchestrator(storage, context, make_agents(storage))
    assert event_types(storage, context) == [
        "queued",
        "running",
        "role_started", "role_finished",  # planner
        "role_started", "role_finished",  # coder
        "role_started", "role_finished",  # tester
        "checks",
        "completed",
    ]


def test_plan_is_handed_to_coder_and_tester(storage, context):
    run_orchestrator(storage, context, make_agents(storage))
    assert storage.get_current_task(context, PLANNER).plan is None
    assert storage.get_current_task(context, CODER).plan == "THE PLAN"
    assert storage.get_current_task(context, TESTER).plan == "THE PLAN"


def test_active_role_is_set_while_each_agent_runs(storage, context):
    seen = []

    async def observe(agent, ctx, recorder):
        seen.append(storage.get_run(ctx.workspace_id, ctx.run_id).active_role)
        if agent.role == TESTER:
            record_check(agent, ctx, passed=True)
        submit(agent, ctx)

    agents = make_agents(storage, planner=observe, coder=observe, tester=observe)
    run_orchestrator(storage, context, agents)
    assert seen == [PLANNER, CODER, TESTER]


def test_status_is_running_while_agents_work(storage, context):
    statuses = []

    async def observe(agent, ctx, recorder):
        statuses.append(storage.get_run(ctx.workspace_id, ctx.run_id).status)
        submit(agent, ctx)

    run_orchestrator(storage, context, make_agents(storage, planner=observe))
    assert statuses == ["running"]


def test_recorder_writes_events_and_usage(storage, context):
    async def planner(agent, ctx, recorder):
        recorder.event("tool_call", "Planner -> getTask")
        recorder.add_usage(input_tokens=10, output_tokens=5)
        submit(agent, ctx)

    run_orchestrator(storage, context, make_agents(storage, planner=planner))
    assert "tool_call" in event_types(storage, context)
    assert storage.get_usage(context).api_calls == 1


# --- Repair loop -------------------------------------------------------------------


def test_failed_tests_trigger_a_repair(storage, context):
    agents = make_agents(storage, tester=scripted_tester(False, True))
    run = run_orchestrator(storage, context, agents)
    assert run.status == "completed"
    assert run.repair_count == 1
    assert run.checks.tests == "passed"
    assert (agents[CODER].calls, agents[TESTER].calls) == (2, 2)
    repair_task = storage.get_current_task(context, CODER)
    assert repair_task.attempt == 2
    # The Coder sees what failed; the plan stays the same.
    assert "log 1" in repair_task.previous_failure
    assert repair_task.plan == "THE PLAN"
    assert "repair" in event_types(storage, context)


def test_planner_is_not_rerun_during_repairs(storage, context):
    agents = make_agents(storage, tester=scripted_tester(False, True))
    run_orchestrator(storage, context, agents)
    assert agents[PLANNER].calls == 1


def test_run_fails_when_repairs_are_exhausted(storage, context):
    agents = make_agents(storage, tester=scripted_tester(False, False, False))
    run = run_orchestrator(storage, context, agents, max_repairs=2)
    assert run.status == "failed"
    assert run.repair_count == 2
    assert run.checks.tests == "failed"
    assert run.active_role is None
    assert "2 repair" in run.error
    # First attempt plus two repairs.
    assert (agents[CODER].calls, agents[TESTER].calls) == (3, 3)
    assert event_types(storage, context)[-1] == "failed"


def test_zero_repairs_means_a_single_attempt(storage, context):
    agents = make_agents(storage, tester=scripted_tester(False))
    run = run_orchestrator(storage, context, agents, max_repairs=0)
    assert run.status == "failed"
    assert agents[CODER].calls == 1


# --- Results come from checks.json, not from agents' claims ---------------------------


def test_tester_claiming_success_does_not_override_failed_checks(storage, context):
    async def optimistic_tester(agent, ctx, recorder):
        record_check(agent, ctx, passed=False)
        submit(agent, ctx, summary="All good!", outcome="success")

    agents = make_agents(storage, tester=optimistic_tester)
    run = run_orchestrator(storage, context, agents, max_repairs=0)
    assert run.status == "failed"
    assert run.checks.tests == "failed"


def test_tester_must_run_the_checks(storage, context):
    async def lazy_tester(agent, ctx, recorder):
        submit(agent, ctx, summary="Looks fine", outcome="success")

    run = run_orchestrator(storage, context, make_agents(storage, tester=lazy_tester))
    assert run.status == "failed"
    assert run.checks.tests == "not_run"
    assert "without running the checks" in run.error


def test_checks_from_an_earlier_attempt_do_not_count(storage, context):
    # Attempt 1 fails; in attempt 2 the Tester runs nothing. The passing
    # result must come from the current attempt, so the run fails.
    async def tester(agent, ctx, recorder):
        if agent.calls == 1:
            record_check(agent, ctx, passed=False)
        submit(agent, ctx)

    run = run_orchestrator(storage, context, make_agents(storage, tester=tester))
    assert run.status == "failed"
    assert "without running the checks" in run.error


# --- Agent failures ----------------------------------------------------------------


@pytest.mark.parametrize("role", [PLANNER, CODER, TESTER])
def test_agent_that_does_not_submit_fails_the_run(storage, context, role):
    async def silent(agent, ctx, recorder):
        if agent.role == TESTER:
            record_check(agent, ctx, passed=True)

    agents = make_agents(storage, **{role.value: silent})
    run = run_orchestrator(storage, context, agents)
    assert run.status == "failed"
    assert run.active_role is None
    assert "without submitting a result" in run.error
    assert role.value.capitalize() in run.error


def test_agent_exception_fails_the_run(storage, context):
    async def crash(agent, ctx, recorder):
        raise RuntimeError("model unavailable")

    run = run_orchestrator(storage, context, make_agents(storage, coder=crash))
    assert run.status == "failed"
    assert run.active_role is None
    assert "Coder" in run.error and "model unavailable" in run.error
    assert event_types(storage, context)[-1] == "failed"


# --- Scheduler ---------------------------------------------------------------------


def test_scheduler_runs_one_run_at_a_time_per_workspace(storage):
    workspace = storage.create_workspace("Demo")
    first = storage.create_run(workspace.id, "first", [])
    second = storage.create_run(workspace.id, "second", [])
    active = 0
    most_active = 0

    async def slow_planner(agent, ctx, recorder):
        nonlocal active, most_active
        active += 1
        most_active = max(most_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        submit(agent, ctx)

    async def main():
        orchestrator = Orchestrator(
            storage, make_agents(storage, planner=slow_planner), max_repairs=0
        )
        scheduler = RunScheduler(orchestrator)
        scheduler.submit(RunContext(workspace.id, first.id))
        scheduler.submit(RunContext(workspace.id, second.id))
        await scheduler.wait_idle()

    asyncio.run(main())
    assert most_active == 1
    for run in (first, second):
        assert storage.get_run(workspace.id, run.id).status == "completed"


def test_scheduler_shutdown_marks_running_runs_failed(storage, context):
    async def hang(agent, ctx, recorder):
        await asyncio.sleep(60)

    async def main():
        orchestrator = Orchestrator(
            storage, make_agents(storage, planner=hang), max_repairs=0
        )
        scheduler = RunScheduler(orchestrator)
        scheduler.submit(context)
        await asyncio.sleep(0.05)
        await scheduler.shutdown()

    asyncio.run(main())
    run = storage.get_run(context.workspace_id, context.run_id)
    assert run.status == "failed"
    assert run.active_role is None
    assert "stopped" in run.error
