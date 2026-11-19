"""The real Planner agent, implemented in stage 4 (see docs/team-responsibilities.md).

Until then the backend runs `placeholder.PlaceholderPlanner`. This class must
follow the contract in `agents/base.py`: read the task with MCP `getTask`, do
the work through MCP tools, and finish with MCP `submitResult`. The Planner's
result summary is the full plan handed to the Coder and the Tester.
"""
from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder


class PlannerAgent:
    role = AgentRole.PLANNER

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        # TODO (stage 4): start an MCP client bound to this run and role, run
        # the Gemini tool loop through the LLM gateway (which records usage via
        # `recorder.add_usage`), log each tool call with
        # `recorder.event("tool_call", ...)`, and submit the plan.
        raise NotImplementedError
