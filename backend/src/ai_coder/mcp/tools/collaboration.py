from ai_coder.models import AgentRole, AgentResult, AgentTask, RunContext


class CollaborationTools:
    async def get_task(self, context: RunContext, role: AgentRole) -> AgentTask:
        # TODO: Read the assigned task from the workspace/run task store.
        raise NotImplementedError

    async def submit_result(self, result: AgentResult) -> None:
        # TODO: Verify bound context/role and persist the result for handoff.
        # TODO: Finalize a structured outcome field with execution references;
        # never trust agent summaries as proof that tests passed.
        raise NotImplementedError
