# Author: Ching Kao
# Student ID: 85768427
"""The provider boundary used by the shared model-call gateway."""

from typing import Protocol


class ModelAdapter(Protocol):
    model: str
    timeout_seconds: float

    async def configuration(self) -> dict:
        """Return local configuration status, without testing provider acceptance."""
        ...

    def set_api_key(self, key: str) -> None:
        """Set an in-memory key, or raise LLMError when unsupported."""
        ...

    def call_metadata(self) -> dict:
        """Return safe model settings for call records, never credentials or content."""
        ...

    async def complete(
        self, messages: list[dict], *, system_instruction: str, tools: list[dict] | None = None,
    ) -> dict:
        """Check local prerequisites and return a normalized model decision."""
        ...
