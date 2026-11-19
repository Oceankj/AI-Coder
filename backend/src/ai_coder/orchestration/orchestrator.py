"""Runs one generation: Planner -> Coder -> Tester, with bounded repairs.

Flow of `Orchestrator.run` (one run):

    status = running
    Planner                       -> plan (the Planner's submitted summary)
    attempt 0..max_repairs:
        Coder   (plan, previous failure if this is a repair)
        Tester  (plan)            -> must record a check execution
        checks passed?  -> status = completed, stop
        repairs left?   -> repairCount += 1, try again with the failure log
        otherwise       -> status = failed
    any error           -> status = failed, error = readable reason
    always              -> activeRole = None

Agents never talk to each other directly: the orchestrator publishes a task in
tasks.json, the agent reads it and submits a result there (blackboard pattern).
Whether tests passed is decided from checks.json, which only `runChecks` writes,
never from the agent's own claim.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

from ai_coder.agents.base import Agent
from ai_coder.models import AgentRole, AgentTask, CheckExecution, RunContext
from ai_coder.orchestration.recorder import RunRecorder
from ai_coder.storage.repository import FileStorage

logger = logging.getLogger(__name__)

# Short role directives stored in each task. The detailed prompts belong to the
# agents themselves (stage 4/5); these only say what this particular task is.
PLANNER_INSTRUCTIONS = (
    "Turn the description and requirements into a precise plan: the files to "
    "create, every function with its inputs and outputs, and the rules the "
    "tests must check. Submit the full plan as your result summary."
)
CODER_INSTRUCTIONS = (
    "Implement the plan. Use exactly the file and function names in the plan."
)
CODER_REPAIR_INSTRUCTIONS = (
    "The tests failed (see previousFailure). Fix the application code so the "
    "tests pass. Do not change the tests."
)
TESTER_INSTRUCTIONS = (
    "Write tests from the requirements and the plan only, without reading the "
    "implementation. Then call runChecks and submit what happened."
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
    ) -> None:
        missing = set(AgentRole) - set(agents)
        if missing:
            raise ValueError(f"Missing agents: {sorted(r.value for r in missing)}")
        self._storage = storage
        self._agents = dict(agents)
        self._max_repairs = max_repairs

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
            context, AgentRole.PLANNER, PLANNER_INSTRUCTIONS
        )
        plan = planner_task.result.summary
        previous_failure: str | None = None

        for attempt in range(self._max_repairs + 1):
            repairing = attempt > 0
            await self._run_role(
                context,
                AgentRole.CODER,
                CODER_REPAIR_INSTRUCTIONS if repairing else CODER_INSTRUCTIONS,
                plan=plan,
                previous_failure=previous_failure,
            )
            execution = await self._run_tester(context, plan, repairing)
            self._storage.update_run(
                context, checks={"build": "not_run", "tests": execution.outcome}
            )
            self._storage.append_event(
                context,
                "checks",
                f"Tests {execution.outcome}: {execution.passed} passed, "
                f"{execution.failed} failed.",
            )
            if execution.outcome == "passed":
                self._storage.update_run(context, status="completed", active_role=None)
                self._storage.append_event(context, "completed", "Run completed.")
                return
            if attempt < self._max_repairs:
                self._storage.update_run(context, repair_count=attempt + 1)
                self._storage.append_event(
                    context,
                    "repair",
                    f"Tests failed; starting repair {attempt + 1} of {self._max_repairs}.",
                )
                previous_failure = _failure_report(execution)

        raise RunFailure(
            f"Tests still failed after {self._max_repairs} repair round(s)."
        )

    async def _run_tester(
        self, context: RunContext, plan: str, repairing: bool
    ) -> CheckExecution:
        """Run the Tester and return the check execution it recorded."""
        executions_before = len(self._storage.list_check_executions(context))
        await self._run_role(
            context,
            AgentRole.TESTER,
            TESTER_RERUN_INSTRUCTIONS if repairing else TESTER_INSTRUCTIONS,
            plan=plan,
        )
        new_executions = self._storage.list_check_executions(context)[executions_before:]
        if not new_executions:
            # Only executions from this attempt count; an older passing result
            # must never be reused.
            raise RunFailure("The Tester finished without running the checks.")
        return new_executions[-1]

    async def _run_role(
        self,
        context: RunContext,
        role: AgentRole,
        instructions: str,
        *,
        plan: str | None = None,
        previous_failure: str | None = None,
    ) -> AgentTask:
        """Publish the role's task, run its agent, and return the submitted task."""
        name = role.value.capitalize()
        storage = self._storage
        storage.publish_task(
            context, role, instructions, plan=plan, previous_failure=previous_failure
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
