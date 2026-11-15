"""Persistence boundary. All run records use a workspace/run composite key."""
from typing import Any, Protocol
from ai_coder.models import RunContext


class RunRepository(Protocol):
    async def get(self, context: RunContext) -> dict[str, Any]: ...
    async def save(self, context: RunContext, record: dict[str, Any]) -> None: ...

# TODO: Persist workspace metadata, task handoffs, events, artifacts, and usage.
# TODO: Choose storage and verify workspace isolation on every read and write.
