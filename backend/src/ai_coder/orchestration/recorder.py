"""What an agent may record about its run.

The orchestrator gives each agent a `RunRecorder` instead of the whole
`FileStorage`. Agents (and the LLM gateway they use) can add progress events
and usage, but cannot change the run's status or checks: those belong to the
orchestrator.
"""
from __future__ import annotations

from ai_coder.models import RunContext, RunEvent, Usage
from ai_coder.storage.repository import FileStorage


class RunRecorder:
    def __init__(self, storage: FileStorage, context: RunContext) -> None:
        self._storage = storage
        self.context = context

    def event(self, type: str, message: str) -> RunEvent:
        """Add a progress event shown in the UI's run log.

        Use type "tool_call" for each MCP tool call, with a message such as
        "Coder -> writeFile(index.html)", so the demo shows MCP traffic.
        """
        return self._storage.append_event(self.context, type, message)

    def add_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int | None = None,
    ) -> Usage:
        """Count one LLM API call (retries included) and its tokens.

        Pass `total_tokens` when the provider reports more than input + output
        (for example Gemini thinking tokens).
        """
        return self._storage.add_usage(
            self.context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
