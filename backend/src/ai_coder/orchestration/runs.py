# Author: Ching Kao
# Student ID: 85768427
"""Commands shared by HTTP and the chat Coordinator."""

from ai_coder.agents.tester import Decision
from ai_coder.config import Provider
from ai_coder.models import RunContext
from ai_coder.workspaces.checks import test_path_failure, test_setup_failure


class RunService:
    def __init__(self, storage, scheduler):
        self.storage = storage
        self.scheduler = scheduler

    def start(self, workspace_id, description, requirements, *, provider: Provider = Provider.GEMINI):
        run = self.storage.create_run(workspace_id, description, requirements, provider=provider)
        self.scheduler.submit(RunContext(workspace_id, run.id))
        return run

    def resume(self, context, clarification):
        run = self.storage.get_run(context.workspace_id, context.run_id)
        if not run or run.status != "blocked" or not run.continuation:
            raise ValueError("Only a blocked run can accept clarification.")
        state = {**run.continuation, "clarification": clarification, "repair_start_count": run.repair_count}
        if state.get("resume_node") in {"code", "diagnose", "red_review", "tests"}:
            checks = self.storage.list_check_executions(context)
            matches_checkpoint = checks and checks[-1].id == (state.get("execution") or {}).get("id")
            if (matches_checkpoint and checks[-1].outcome == "passed" and state.get("resume_node") == "tests"
                    and (state.get("assessment") or {}).get("decision") == Decision.TEST_INVALID):
                state["resume_node"] = "red_review"
            elif matches_checkpoint and checks[-1].outcome == "failed":
                project = self.storage.project_dir(context)
                log = checks[-1].log
                error = test_path_failure(project, log) or test_setup_failure(project, log)
                if error:
                    state.update(
                        resume_node="tests",
                        assessment={"decision": Decision.TEST_INVALID.value, "reason": error},
                        test_setup_error=error,
                    )
                elif (run.repair_count > 0 and (run.error or "").startswith("Repair budget exhausted.")
                      and state.get("resume_node") in {"code", "tests"}):
                    state.update(resume_node="diagnose", reassess_repair=True)
        run = self.storage.update_run(
            context, status="queued", error=None, continuation=state, coordinator_report=None
        )
        self.scheduler.submit(context)
        return run
