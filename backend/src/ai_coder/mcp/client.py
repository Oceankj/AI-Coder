"""SDK-neutral MCP client boundary; no MCP transport is implemented yet."""
from typing import Any, Protocol


class MCPClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """TODO: Call a real MCP server with a server-bound RunContext."""
        ...

    async def close(self) -> None:
        ...
