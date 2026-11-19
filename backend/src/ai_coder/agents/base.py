"""The interface every agent implements; the orchestrator depends only on this.

Contract (see docs/backend-spec.md, "Agent interface"):

1. Before `execute` is called, the orchestrator has published this role's task
   in tasks.json and set the run's activeRole to this role.
2. `execute` reads the task (MCP `getTask`), does the role's work through MCP
   tools, and records its result (MCP `submitResult`). The Tester must also
   call MCP `runChecks`, which records a real test execution in checks.json.
3. `execute` returns when the agent is finished. Returning without having
   submitted a result fails the run.
4. Raising an exception fails the run; the exception message is shown to the
   user, so keep it readable.
5. Each agent creates its own MCP client, because the MCP server is started
   with the agent's role (and run) bound at startup.
6. Progress events and LLM usage go through `recorder`, never directly to
   storage.
"""
from typing import Protocol

from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder


class Agent(Protocol):
    role: AgentRole

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        """Read the task, do the role's work, and submit the result."""
        ...
