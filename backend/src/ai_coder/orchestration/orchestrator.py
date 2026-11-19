"""Runs one generation: plan once, then build and test one feature at a time.

Flow of `Orchestrator.run` (one run):

    status = running
    Planner                       -> plan text + ordered feature list (1..max_features)
    for each feature, in order:
        Coder   (plan, feature)    -> adds the feature to the existing code
        Tester  (plan, feature)    -> adds tests for it, runs ALL tests
        tests passed?        -> next feature
        repair budget left?  -> Coder (repair, with the failing output),
                                Tester (re-run, tests unchanged), check again
        otherwise            -> status = failed; later features never start
    all features passed      -> status = completed
    any error                -> status = failed, error = readable reason
    always                   -> activeRole = None

The repair budget (`max_repairs`) is shared by the whole run, not per feature,
so the number of LLM calls stays bounded. The Tester always runs every test,
so a new feature that breaks an earlier one is caught.

Agents never talk to each other directly: the orchestrator publishes a task in
tasks.json, the agent reads it and submits a result there (blackboard pattern).
Whether tests passed is decided from checks.json, which only `runChecks` writes,
never from the agent's own claim.

The orchestrator is ordinary code, not an LLM: assigning and monitoring work
follows fixed rules, so it is predictable, testable, and costs no API calls.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

from ai_coder.agents.base import Agent
from ai_coder.models import (
    AgentRole,
    AgentTask,
    CheckExecution,
    PlannedFeature,
    RunContext,
    TaskFeature,
)
from ai_coder.orchestration.recorder import RunRecorder
from ai_coder.storage.repository import FileStorage

logger = logging.getLogger(__name__)

# Short role directives stored in each task. The detailed prompts belong to the
# agents themselves (stage 4/5); these only say what this particular task is.
PLANNER_INSTRUCTIONS = (
    "Turn the description and requirements into a precise plan: the files, every "
    "function with its inputs and outputs, and the rules the tests must check. "
    "Split the work into an ordered list of {max_features} or fewer features that "
    "can be built and tested one at a time, each with a short title and a "
    "description. Submit the plan as the summary and the list as features."
)
CODER_INSTRUCTIONS = (
    "Implement only this feature, on top of the existing code. Keep earlier "
    "features working and use exactly the file and function names in the plan."
)
CODER_REPAIR_INSTRUCTIONS = (
    "The tests failed after this feature was added (see previousFailure). Fix the "
    "application code so all tests pass. Do not change the tests."
)
TESTER_INSTRUCTIONS = (
    "Add tests for this feature from the requirements and the plan only, without "
    "reading the implementation. Keep the existing tests. Then call runChecks, "
    "which runs all tests, and submit what happened."
)
TESTER_RERUN_INSTRUCTIONS = (
    "The Coder repaired the code. Do not change the tests; call runChecks again "
    "and submit what happened."
)

STOPPED_ERROR = "The backend stopped before this run finished."
MAX_ERROR_CHARS = 500


class RunFailure(Exception):
    """A reason to fail the run, with a message meant for the user."""


class Orchestrator:
    def __init__(
        self,
        storage: FileStorage,
        agents: Mapping[AgentRole, Agent],
        *,
        max_repairs: int,
        max_features: int,
    ) -> None:
        missing = set(AgentRole) - set(agents)
        if missing:
            raise ValueError(f"Missing agents: {sorted(r.value for r in missing)}")
        self._storage = storage
        self._agents = dict(agents)
        self._max_repairs = max_repairs
        self._max_features = max_features

    async def run(self, context: RunContext) -> None:
        """Execute the run to completion. Never raises, except on cancellation."""
        storage = self._storage
        storage.update_run(context, status="running")
        storage.append_event(context, "running", "Run started.")
        try:
            await self._generate(context)
        except asyncio.CancelledError:
            self._finish_failed(context, STOPPED_ERROR)
            raise
        except RunFailure as failure:
            self._finish_failed(context, str(failure))
        except Exception as error:  # an agent or the system crashed
            logger.exception("Run %s failed unexpectedly", context.run_id)
            self._finish_failed(context, _describe(error))

    async def _generate(self, context: RunContext) -> None:
        planner_task = await self._run_role(
            context,
            AgentRole.PLANNER,
            PLANNER_INSTRUCTIONS.format(max_features=self._max_features),
        )
        plan = planner_task.result.summary
        features = self._checked_features(planner_task.result.features)

        for number, planned in enumerate(features, start=1):
            feature = TaskFeature(
                number=number,
                total=len(features),
                title=planned.title,
                description=planned.description,
            )
            await self._build_feature(context, plan, feature)

        self._storage.update_run(context, status="completed", active_role=None)
        self._storage.append_event(context, "completed", "Run completed.")

    async def _build_feature(
        self, context: RunContext, plan: str, feature: TaskFeature
    ) -> None:
        """Coder -> Tester for one feature, repairing while the budget lasts."""
        storage = self._storage
        label = f"Feature {feature.number}/{feature.total}"
        storage.append_event(context, "feature_started", f"{label} started: {feature.title}")
        previous_failure: str | None = None

        while True:
            repairing = previous_failure is not None
            await self._run_role(
                context,
                AgentRole.CODER,
                CODER_REPAIR_INSTRUCTIONS if repairing else CODER_INSTRUCTIONS,
                plan=plan,
                feature=feature,
                repair=repairing,
                previous_failure=previous_failure,
            )
            execution = await self._run_tester(context, plan, feature, repairing)
            storage.update_run(
                context, checks={"build": "not_run", "tests": execution.outcome}
            )
            storage.append_event(
                context,
                "checks",
                f"{label} tests {execution.outcome}: {execution.passed} passed, "
                f"{execution.failed} failed.",
            )
            if execution.outcome == "passed":
                storage.append_event(
                    context, "feature_completed", f"{label} completed: {feature.title}"
                )
                return

            used = self._current_repair_count(context)
            if used >= self._max_repairs:
                raise RunFailure(
                    f"Feature {feature.number} of {feature.total} ({feature.title}) "
                    f"failed its tests and no repair rounds are left "
                    f"(limit {self._max_repairs} per run)."
                )
            storage.update_run(context, repair_count=used + 1)
            storage.append_event(
                context,
                "repair",
                f"{label} tests failed; starting repair {used + 1} of {self._max_repairs}.",
            )
            previous_failure = _failure_report(execution)

    async def _run_tester(
        self, context: RunContext, plan: str, feature: TaskFeature, repairing: bool
    ) -> CheckExecution:
        """Run the Tester and return the check execution it recorded."""
        executions_before = len(self._storage.list_check_executions(context))
        await self._run_role(
            context,
            AgentRole.TESTER,
            TESTER_RERUN_INSTRUCTIONS if repairing else TESTER_INSTRUCTIONS,
            plan=plan,
            feature=feature,
            repair=repairing,
        )
        new_executions = self._storage.list_check_executions(context)[executions_before:]
        if not new_executions:
            # Only executions from this attempt count; an older passing result
            # (from an earlier attempt or feature) must never be reused.
            raise RunFailure("The Tester finished without running the checks.")
        return new_executions[-1]

    async def _run_role(
        self,
        context: RunContext,
        role: AgentRole,
        instructions: str,
        *,
        plan: str | None = None,
        feature: TaskFeature | None = None,
        repair: bool = False,
        previous_failure: str | None = None,
    ) -> AgentTask:
        """Publish the role's task, run its agent, and return the submitted task."""
        name = role.value.capitalize()
        storage = self._storage
        storage.publish_task(
            context,
            role,
            instructions,
            plan=plan,
            feature=feature,
            repair=repair,
            previous_failure=previous_failure,
        )
        storage.update_run(context, active_role=role)
        storage.append_event(context, "role_started", f"{name} started.")
        try:
            await self._agents[role].execute(context, RunRecorder(storage, context))
        except (asyncio.CancelledError, RunFailure):
            raise
        except Exception as error:
            logger.exception("%s failed in run %s", name, context.run_id)
            raise RunFailure(f"{name} failed: {_describe(error)}") from error

        task = storage.get_current_task(context, role)
        if task is None or task.status != "submitted" or task.result is None:
            raise RunFailure(f"The {name} finished without submitting a result.")
        storage.append_event(
            context, "role_finished", f"{name} finished: {_first_line(task.result.summary)}"
        )
        return task

    def _checked_features(self, features: list[PlannedFeature]) -> list[PlannedFeature]:
        """The Planner's feature list, or a RunFailure explaining what is wrong."""
        if not 1 <= len(features) <= self._max_features:
            raise RunFailure(
                f"The Planner must split the work into 1 to {self._max_features} "
                f"features; it returned {len(features)}."
            )
        for number, feature in enumerate(features, start=1):
            if not feature.title.strip():
                raise RunFailure(f"The Planner's feature {number} has a blank title.")
        return features

    def _current_repair_count(self, context: RunContext) -> int:
        run = self._storage.get_run(context.workspace_id, context.run_id)
        return run.repair_count if run else 0

    def _finish_failed(self, context: RunContext, error: str) -> None:
        self._storage.update_run(
            context, status="failed", active_role=None, error=error[:MAX_ERROR_CHARS]
        )
        self._storage.append_event(context, "failed", error[:MAX_ERROR_CHARS])


def _failure_report(execution: CheckExecution) -> str:
    """What the Coder receives as `previousFailure` on a repair task."""
    timeout = " The test run timed out." if execution.timed_out else ""
    return (
        f"{execution.passed} passed, {execution.failed} failed.{timeout}\n"
        f"{execution.log}"
    )


def _describe(error: Exception) -> str:
    message = str(error) or "no details"
    return f"{type(error).__name__}: {message}"


def _first_line(text: str, limit: int = 120) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"
