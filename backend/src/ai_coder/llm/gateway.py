"""Single boundary for model calls and usage accounting across agents."""
from ai_coder.models import AgentRole, RunContext


class LLMGateway:
    async def complete(self, context: RunContext, role: AgentRole, messages: list[dict]):
        # TODO: Call configured provider; persist call count and provider token
        # usage per workspace/run/role, including retries. Mark unknown usage
        # explicitly rather than fabricating zero-token records.
        raise NotImplementedError
