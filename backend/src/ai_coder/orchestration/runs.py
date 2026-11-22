# Author: Ching Kao
# Student ID: 85768427
"""Commands shared by HTTP and the chat Coordinator."""

from ai_coder.models import RunContext


class RunService:
    def __init__(self, storage, scheduler):
        self.storage = storage
        self.scheduler = scheduler

    def start(self, workspace_id, description, requirements):
        run = self.storage.create_run(workspace_id, description, requirements)
        self.scheduler.submit(RunContext(workspace_id, run.id))
        return run

    def resume(self, context, clarification):
        run = self.storage.get_run(context.workspace_id, context.run_id)
        if not run or run.status != "blocked" or not run.continuation:
            raise ValueError("Only a blocked run can accept clarification.")
        state = {**run.continuation, "clarification": clarification}
        run = self.storage.update_run(
            context, status="queued", error=None, continuation=state, coordinator_report=None
        )
        self.scheduler.submit(context)
        return run
