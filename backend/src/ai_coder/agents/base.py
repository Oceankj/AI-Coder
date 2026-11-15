from typing import Protocol
from ai_coder.models import AgentRole, RunContext
from ai_coder.mcp.client import MCPClient


class Agent(Protocol):
    role: AgentRole

    async def execute(self, context: RunContext, tools: MCPClient) -> None:
        """Read tasks, perform role work, and submit results through MCP."""
        ...
