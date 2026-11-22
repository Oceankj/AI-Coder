"""The single model-call entry point for chat and run agents."""
import asyncio
from time import perf_counter
from typing import Literal
from uuid import uuid4

from ai_coder.llm.errors import LLMError
from ai_coder.llm.gemini import GeminiAdapter
from ai_coder.models import AICallCaller, AICallEvent, AgentRole, RunContext
from ai_coder.storage.records import JsonlRecords


class LLMGateway:
    def __init__(self, provider: GeminiAdapter, records: JsonlRecords):
        self._provider = provider
        self._records = records

    @property
    def configured(self) -> bool:
        return self._provider.configured

    @property
    def model(self) -> str:
        return self._provider.model

    def set_api_key(self, key: str) -> None:
        self._provider.set_api_key(key)

    async def complete(
        self, messages: list[dict], *, system_instruction: str,
        context: RunContext | None = None, role: AgentRole | Literal["coordinator"] | None = None,
        request_id: str | None = None, tools: list[dict] | None = None,
    ) -> dict:
        if (context is None) != (role is None):
            raise ValueError("Agent model calls require both run context and role.")
        call_id = uuid4().hex
        fields = {
            "callId": call_id, "requestId": request_id,
            "caller": AICallCaller.AGENT if context else AICallCaller.CHAT, "model": self.model,
            "messageCount": len(messages),
            "inputCharacters": sum(len(message["content"]) for message in messages),
        }
        if context:
            fields.update(workspaceId=context.workspace_id, runId=context.run_id, role=role.value if isinstance(role, AgentRole) else role)
        started = perf_counter()
        await self._records.write({**fields, "event": AICallEvent.STARTED})
        try:
            if not self.configured:
                raise LLMError(409, "GEMINI_KEY_REQUIRED", "Add your Gemini API key to start chatting.")
            async with asyncio.timeout(self._provider.timeout_seconds):
                options = {"tools": tools} if tools else {}
                result = await self._provider.complete(messages, system_instruction=system_instruction, **options)
        except asyncio.CancelledError:
            await self._records.write({**fields, "event": AICallEvent.CANCELLED, "durationMs": round((perf_counter() - started) * 1000, 2)})
            raise
        except Exception as original:
            error = _public_error(original)
            await self._failure(fields, error, started)
            if isinstance(original, LLMError):
                raise
            raise error from None
        await self._records.write({
            **fields, "event": AICallEvent.COMPLETED, "status": 200,
            "durationMs": round((perf_counter() - started) * 1000, 2),
            "resolvedModel": result["resolvedModel"], **result["timing"], **result["usage"],
        })
        return result

    async def _failure(self, fields: dict, error: LLMError, started: float) -> None:
        safe = {key: error.metadata[key] for key in ("providerStatus", "providerMs", "adapterMs") if key in error.metadata}
        await self._records.write({**fields, "event": AICallEvent.FAILED, "status": error.status,
                                  "errorCode": error.code, "durationMs": round((perf_counter() - started) * 1000, 2), **safe})


def _public_error(error: Exception) -> LLMError:
    """Keep provider errors; turn unexpected failures into safe API errors."""
    if isinstance(error, LLMError):
        return error
    if isinstance(error, TimeoutError):
        return LLMError(504, "GEMINI_TIMEOUT", "Gemini took too long to respond. Please try again.")
    return LLMError(502, "LLM_UNAVAILABLE", "The AI service could not complete this request. Please try again.")
