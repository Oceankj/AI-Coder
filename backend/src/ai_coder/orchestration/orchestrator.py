"""Coordinates role execution; task exchange goes through MCP.

Placeholder until step 4 of the backend plan (see WORK_LOG.md). The run's
input is read from run.json, so only the run context is needed.
"""
from ai_coder.models import RunContext


class Orchestrator:
    async def run(self, context: RunContext):
        # TODO: Serialize runs within one workspace.
        # TODO: Publish initial task; execute Planner -> Coder -> Tester.
        # TODO: Exchange task/result data through MCP collaboration tools.
        # TODO: On test failure, retry Coder -> Tester with a bounded repair count.
        # TODO: Persist events/usage and package outputs; release resources.
        raise NotImplementedError
