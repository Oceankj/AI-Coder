"""The real Tester agent, implemented in stage 4 (see docs/team-responsibilities.md).

Until then the backend runs `placeholder.PlaceholderTester`. This class must
follow the contract in `agents/base.py`: read the task with MCP `getTask`,
write tests from the requirements and plan without reading the implementation,
call MCP `runChecks` (the orchestrator fails the run if it is not called), and
finish with MCP `submitResult`.
"""
from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder


class TesterAgent:
    role = AgentRole.TESTER

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        # TODO (stage 4): start an MCP client bound to this run and role, run
        # the Gemini tool loop through the LLM gateway (which records usage via
        # `recorder.add_usage`), log each tool call with
        # `recorder.event("tool_call", ...)`, call runChecks, and submit.
        raise NotImplementedError
