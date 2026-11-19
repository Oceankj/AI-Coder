"""The real Coder agent, implemented in stage 4 (see docs/team-responsibilities.md).

Until then the backend runs `placeholder.PlaceholderCoder`. This class must
follow the contract in `agents/base.py`: read the task with MCP `getTask`, do
the work through MCP tools, and finish with MCP `submitResult`. On a repair
task, `previousFailure` holds the failing test output; fix the code, not the
tests.
"""
from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder


class CoderAgent:
    role = AgentRole.CODER

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        # TODO (stage 4): start an MCP client bound to this run and role, run
        # the Gemini tool loop through the LLM gateway (which records usage via
        # `recorder.add_usage`), log each tool call with
        # `recorder.event("tool_call", ...)`, and submit the result.
        raise NotImplementedError
