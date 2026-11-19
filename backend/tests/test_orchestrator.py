"""Step 4: orchestrator and scheduler (feature-by-feature flow).

The orchestrator is tested with scripted agents that do exactly what each test
needs (plan N features, submit or not, record passing or failing checks,
raise). This pins the rules in docs/backend-spec.md:

- The Planner runs once and splits the work into 1..max_features features.
- Each feature goes Coder -> Tester; a failing feature is repaired
  (Coder -> Tester again) while the run's shared repair budget lasts.
- A feature that cannot be repaired stops the run; later features never start.
- Whether tests passed comes from checks.json executions of the current
  attempt only, never from the agent's own claim.
- Every failure ends the run as "failed" with a readable error, and
  activeRole is always cleared at the end.
"""
import asyncio

import pytest

from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.orchestrator import Orchestrator, format_duration
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
        self.tasks = []  # the task this agent saw on each call

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        self.calls += 1
        self.tasks.append(self.storage.get_current_task(context, self.role))
        await self.script(self, context, recorder)


def submit(agent, context, summary="done", outcome="success", features=None):
    agent.storage.submit_result(
        context,
        agent.role,
        summary=summary,
        artifact_paths=[],
        outcome=outcome,
        features=features,
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


def planner_with(*titles):
    """A Planner that splits the work into the given features."""

    async def plan(agent, context, recorder):
        features = [{"title": t, "description": f"About {t}"} for t in titles]
        submit(agent, context, summary="THE PLAN", features=features)

    return plan


async def code(agent, context, recorder):
    submit(agent, context, summary="wrote code")


async def passing_tester(agent, context, recorder):
    record_check(agent, context, passed=True)
    submit(agent, context, summary="ran tests")


def scripted_tester(*results: bool):
    """A Tester that records the given check results, one per call."""

    async def test(agent, context, recorder):
        record_check(agent, context, passed=results[agent.calls - 1], log=f"log {agent.calls}")
        submit(agent, context, summary="ran tests")

    return test


def make_agents(
    storage, planner=planner_with("Genres"), coder=code, tester=passing_tester
):
    return {
        PLANNER: ScriptedAgent(PLANNER, storage, planner),
        CODER: ScriptedAgent(CODER, storage, coder),
        TESTER: ScriptedAgent(TESTER, storage, tester),
    }


def run_orchestrator(
    storage, context, agents, max_repairs=3, max_features=4, agent_timeout_seconds=5.0
):
    orchestrator = Orchestrator(
        storage,
        agents,
        max_repairs=max_repairs,
        max_features=max_features,
        agent_timeout_seconds=agent_timeout_seconds,
    )
    asyncio.run(orchestrator.run(context))
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


def test_each_feature_runs_coder_then_tester(storage, context):
    agents = make_agents(storage, planner=planner_with("Genres", "Mood", "Export"))
    run = run_orchestrator(storage, context, agents)
    assert run.status == "completed"
    assert (agents[PLANNER].calls, agents[CODER].calls, agents[TESTER].calls) == (1, 3, 3)


def test_events_for_two_features(storage, context):
    agents = make_agents(storage, planner=planner_with("Genres", "Mood"))
    run_orchestrator(storage, context, agents)
    feature = [
        "feature_started",
        "role_started", "role_finished",  # coder
        "role_started", "role_finished",  # tester
        "checks",
        "feature_completed",
    ]
    assert event_types(storage, context) == [
        "queued",
        "running",
        "role_started", "role_finished",  # planner
        *feature,
        *feature,
        "completed",
    ]


def test_feature_events_name_the_feature(storage, context):
    agents = make_agents(storage, planner=planner_with("Genres", "Mood"))
    run_orchestrator(storage, context, agents)
    started = [e.message for e in storage.list_events(context) if e.type == "feature_started"]
    assert started == ["Feature 1/2 started: Genres", "Feature 2/2 started: Mood"]


def test_tasks_carry_plan_and_feature(storage, context):
    agents = make_agents(storage, planner=planner_with("Genres", "Mood"))
    run_orchestrator(storage, context, agents)
    for role in (CODER, TESTER):
        tasks = agents[role].tasks
        assert [t.plan for t in tasks] == ["THE PLAN", "THE PLAN"]
        assert [(t.feature.number, t.feature.total, t.feature.title) for t in tasks] == [
            (1, 2, "Genres"),
            (2, 2, "Mood"),
        ]
        assert tasks[1].feature.description == "About Mood"
        assert [t.repair for t in tasks] == [False, False]
    assert agents[PLANNER].tasks[0].feature is None


def test_active_role_follows_the_work(storage, context):
    seen = []

    async def observe(agent, ctx, recorder):
        seen.append(storage.get_run(ctx.workspace_id, ctx.run_id).active_role)
        if agent.role == TESTER:
            record_check(agent, ctx, passed=True)
        submit(agent, ctx)

    agents = make_agents(
        storage,
        planner=planner_with("Genres", "Mood"),
        coder=observe,
        tester=observe,
    )
    run_orchestrator(storage, context, agents)
    assert seen == [CODER, TESTER, CODER, TESTER]


def test_status_is_running_while_agents_work(storage, context):
    statuses = []

    async def observe(agent, ctx, recorder):
        statuses.append(storage.get_run(ctx.workspace_id, ctx.run_id).status)
        await planner_with("Genres")(agent, ctx, recorder)

    run_orchestrator(storage, context, make_agents(storage, planner=observe))
    assert statuses == ["running"]


def test_recorder_writes_events_and_usage(storage, context):
    async def planner(agent, ctx, recorder):
        recorder.event("tool_call", "Planner -> getTask")
        recorder.add_usage(input_tokens=10, output_tokens=5)
        await planner_with("Genres")(agent, ctx, recorder)

    run_orchestrator(storage, context, make_agents(storage, planner=planner))
    assert "tool_call" in event_types(storage, context)
    assert storage.get_usage(context).api_calls == 1


# --- Planner's feature list ------------------------------------------------------------


def test_planner_without_features_fails_the_run(storage, context):
    run = run_orchestrator(storage, context, make_agents(storage, planner=planner_with()))
    assert run.status == "failed"
    assert "1 to 4 features" in run.error and "returned 0" in run.error


def test_planner_with_too_many_features_fails_the_run(storage, context):
    agents = make_agents(storage, planner=planner_with("a", "b", "c"))
    run = run_orchestrator(storage, context, agents, max_features=2)
    assert run.status == "failed"
    assert "1 to 2 features" in run.error and "returned 3" in run.error
    assert agents[CODER].calls == 0


def test_feature_titles_must_not_be_blank(storage, context):
    run = run_orchestrator(storage, context, make_agents(storage, planner=planner_with("  ")))
    assert run.status == "failed"
    assert "title" in run.error


# --- Repair loop -------------------------------------------------------------------


def test_failing_feature_is_repaired(storage, context):
    agents = make_agents(
        storage,
        planner=planner_with("Genres", "Mood"),
        tester=scripted_tester(True, False, True),  # feature 2 fails once
    )
    run = run_orchestrator(storage, context, agents)
    assert run.status == "completed"
    assert run.repair_count == 1
    coder_tasks = agents[CODER].tasks
    assert [(t.feature.number, t.repair) for t in coder_tasks] == [
        (1, False),
        (2, False),
        (2, True),
    ]
    # The repair task carries the failing output; the plan stays the same.
    assert "log 2" in coder_tasks[2].previous_failure
    assert coder_tasks[2].plan == "THE PLAN"
    assert [t.repair for t in agents[TESTER].tasks] == [False, False, True]
    assert "repair" in event_types(storage, context)


def test_planner_and_finished_features_are_not_rerun(storage, context):
    agents = make_agents(
        storage,
        planner=planner_with("Genres", "Mood"),
        tester=scripted_tester(True, False, True),
    )
    run_orchestrator(storage, context, agents)
    assert agents[PLANNER].calls == 1
    assert [t.feature.number for t in agents[CODER].tasks].count(1) == 1


def test_repair_budget_is_shared_across_features(storage, context):
    # Feature 1 uses one repair, feature 2 uses the second; its next failure
    # finds the budget of 2 empty.
    agents = make_agents(
        storage,
        planner=planner_with("Genres", "Mood"),
        tester=scripted_tester(False, True, False, False),
    )
    run = run_orchestrator(storage, context, agents, max_repairs=2)
    assert run.status == "failed"
    assert run.repair_count == 2
    assert run.checks.tests == "failed"
    assert run.active_role is None
    assert "Feature 2 of 2 (Mood)" in run.error
    assert "no repair rounds are left" in run.error
    assert event_types(storage, context)[-1] == "failed"


def test_unrepairable_feature_stops_later_features(storage, context):
    agents = make_agents(
        storage,
        planner=planner_with("Genres", "Mood", "Export"),
        tester=scripted_tester(False, False),
    )
    run = run_orchestrator(storage, context, agents, max_repairs=1)
    assert run.status == "failed"
    assert {t.feature.number for t in agents[CODER].tasks} == {1}


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


def test_checks_from_an_earlier_feature_do_not_count(storage, context):
    # Feature 1 passes; for feature 2 the Tester runs nothing. Feature 1's
    # passing execution must not be reused, so the run fails.
    async def tester(agent, ctx, recorder):
        if agent.calls == 1:
            record_check(agent, ctx, passed=True)
        submit(agent, ctx)

    agents = make_agents(storage, planner=planner_with("Genres", "Mood"), tester=tester)
    run = run_orchestrator(storage, context, agents)
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


# --- Time limit per agent -------------------------------------------------------------


async def hang(agent, ctx, recorder):
    await asyncio.sleep(60)


def test_agent_that_exceeds_its_time_limit_fails_the_run(storage, context):
    agents = make_agents(storage, coder=hang)
    run = run_orchestrator(storage, context, agents, agent_timeout_seconds=0.05)
    assert run.status == "failed"
    assert run.active_role is None
    assert run.error == "The Coder did not finish within 0.05 seconds."
    assert event_types(storage, context)[-1] == "failed"
    assert agents[TESTER].calls == 0


def test_agents_own_timeout_error_is_not_mistaken_for_the_time_limit(storage, context):
    # e.g. the agent's own HTTP call to Gemini timed out after 30 s: that is
    # an agent failure with its own message, not "did not finish within".
    async def own_timeout(agent, ctx, recorder):
        raise TimeoutError("Gemini request timed out")

    run = run_orchestrator(storage, context, make_agents(storage, coder=own_timeout))
    assert run.status == "failed"
    assert run.error == "Coder failed: TimeoutError: Gemini request timed out"


def test_time_limit_applies_to_each_agent_not_the_whole_run(storage, context):
    # Three agents of 0.04 s each take longer than one limit of 0.1 s together,
    # but each stays within it.
    async def slow(agent, ctx, recorder):
        await asyncio.sleep(0.04)
        if agent.role == PLANNER:
            await planner_with("Genres")(agent, ctx, recorder)
        elif agent.role == TESTER:
            await passing_tester(agent, ctx, recorder)
        else:
            await code(agent, ctx, recorder)

    agents = make_agents(storage, planner=slow, coder=slow, tester=slow)
    run = run_orchestrator(storage, context, agents, agent_timeout_seconds=0.1)
    assert run.status == "completed"


def test_timed_out_agent_is_cancelled_so_it_can_clean_up(storage, context):
    cleaned_up = []

    async def hang_then_clean_up(agent, ctx, recorder):
        try:
            await asyncio.sleep(60)
        finally:
            cleaned_up.append(True)  # e.g. stop the agent's MCP server

    agents = make_agents(storage, planner=hang_then_clean_up)
    run_orchestrator(storage, context, agents, agent_timeout_seconds=0.05)
    assert cleaned_up == [True]


def test_no_time_limit_when_none(storage, context):
    async def short_wait(agent, ctx, recorder):
        await asyncio.sleep(0.02)
        await planner_with("Genres")(agent, ctx, recorder)

    agents = make_agents(storage, planner=short_wait)
    run = run_orchestrator(storage, context, agents, agent_timeout_seconds=None)
    assert run.status == "completed"


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(600, "10 minutes"), (60, "1 minute"), (90, "90 seconds"), (1, "1 second"), (0.05, "0.05 seconds")],
)
def test_time_limit_is_described_readably(seconds, text):
    assert format_duration(seconds) == text


def test_timed_out_run_releases_the_workspace(storage):
    workspace = storage.create_workspace("Demo")
    first = storage.create_run(workspace.id, "first", [])
    second = storage.create_run(workspace.id, "second", [])

    async def hang_only_first_run(agent, ctx, recorder):
        if ctx.run_id == first.id:
            await asyncio.sleep(60)
        await planner_with("Genres")(agent, ctx, recorder)

    async def main():
        orchestrator = Orchestrator(
            storage,
            make_agents(storage, planner=hang_only_first_run),
            max_repairs=0,
            max_features=4,
            agent_timeout_seconds=0.05,
        )
        scheduler = RunScheduler(orchestrator)
        scheduler.submit(RunContext(workspace.id, first.id))
        scheduler.submit(RunContext(workspace.id, second.id))
        await scheduler.wait_idle()

    asyncio.run(main())
    assert storage.get_run(workspace.id, first.id).status == "failed"
    assert storage.get_run(workspace.id, second.id).status == "completed"


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
        await planner_with("Genres")(agent, ctx, recorder)

    async def main():
        orchestrator = Orchestrator(
            storage,
            make_agents(storage, planner=slow_planner),
            max_repairs=0,
            max_features=4,
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
            storage, make_agents(storage, planner=hang), max_repairs=0, max_features=4
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
