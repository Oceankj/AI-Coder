"""Coordinates role execution; task exchange goes through MCP."""
from ai_coder.models import GenerationRequest, RunContext


class Orchestrator:
    async def run(self, request: GenerationRequest, context: RunContext):
        # TODO: Verify request.workspace_id matches context.workspace_id.
        # TODO: Acquire the workspace write lock; create scoped MCP clients.
        # TODO: Publish initial task; execute Planner -> Coder -> Tester.
        # TODO: Exchange task/result data through MCP collaboration tools.
        # TODO: On test failure, retry Coder -> Tester with a bounded repair count.
        # TODO: Persist events/usage and package outputs; release resources.
        raise NotImplementedError
