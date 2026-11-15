from ai_coder.models import AgentRole, RunContext
from ai_coder.mcp.client import MCPClient


class TesterAgent:
    role = AgentRole.TESTER

    async def execute(self, context: RunContext, tools: MCPClient) -> None:
        # TODO: Fetch assigned task through MCP, use LLMGateway and allowed
        # tools for this role, then submit the result through MCP.
        raise NotImplementedError
