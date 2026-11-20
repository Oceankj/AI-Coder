"""The interface every agent implements; the orchestrator depends only on this.

Contract (see docs/backend-spec.md, "Agent interface"):

1. Before `execute` is called, the orchestrator has published this role's task
   in tasks.json and set the run's activeRole to this role.
2. `execute` reads the task (MCP `getTask`), does the role's work through MCP
   tools, and records its result (MCP `submitResult`).
   - Planner: submits the plan as its summary and an ordered `features` list
     (1 to max_features items, each with a title and description).
   - Coder: builds only the task's `feature`, on top of the existing code; on
     a `repair` task it fixes the code using `previousFailure`.
   - Tester: adds tests for the task's `feature` (on a `repair` task it leaves
     the tests unchanged) and must call MCP `runChecks`, which runs all tests
     and records a real execution in checks.json.
3. `execute` returns when the agent is finished. Returning without having
   submitted a result fails the run.
4. Raising an exception fails the run; the exception message is shown to the
   user, so keep it readable.
5. Each agent creates its own MCP client, because the MCP server is started
   with the agent's role (and run) bound at startup.
6. Progress events and LLM usage go through `recorder`, never directly to
   storage.
7. Each call has a time limit (Settings.agent_timeout_seconds, default 10
   minutes). When it passes, `execute` is cancelled (asyncio.CancelledError
   is raised inside it) and the run fails; clean up in `finally` blocks.
8. Do slow work with `await`. A blocking call (a synchronous HTTP client,
   time.sleep) freezes the whole server and cannot be interrupted by the time
   limit; wrap unavoidable blocking calls in `await asyncio.to_thread(...)`.
"""
from typing import Protocol

from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder


class Agent(Protocol):
    role: AgentRole

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        """Read the task, do the role's work, and submit the result."""
        ...
