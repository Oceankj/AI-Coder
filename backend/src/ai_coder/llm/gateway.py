# Author: Ching Kao
# Student ID: 85768427
"""The single model-call entry point for chat and run agents."""
import asyncio
from time import perf_counter
from typing import Literal
from uuid import uuid4

from ai_coder.config import GroqModel, Provider
from ai_coder.llm.adapter import ModelAdapter
from ai_coder.llm.errors import LLMError
from ai_coder.models import AICallCaller, AICallEvent, AgentRole, RunContext
from ai_coder.storage.records import JsonlRecords


class LLMGateway:
    def __init__(self, adapters: dict[Provider, ModelAdapter], records: JsonlRecords):
        self._adapters = adapters
        self._records = records

    async def configuration(self, provider: Provider) -> dict:
        return await self._adapters[provider].configuration()

    def set_api_key(self, provider: Provider, key: str) -> None:
        self._adapters[provider].set_api_key(key)

    def set_groq_model(self, model: GroqModel) -> None:
        self._adapters[Provider.GROQ].model = model.value

    async def complete(
        self, messages: list[dict], *, system_instruction: str, provider: Provider = Provider.GEMINI,
        context: RunContext | None = None, role: AgentRole | Literal["coordinator"] | None = None,
        request_id: str | None = None, tools: list[dict] | None = None,
    ) -> dict:
        if (context is None) != (role is None):
            raise ValueError("Agent model calls require both run context and role.")
        adapter = self._adapters[provider]
        call_id = uuid4().hex
        fields = {
            "callId": call_id, "requestId": request_id,
            "caller": AICallCaller.AGENT if context else AICallCaller.CHAT, "model": adapter.model,
            "provider": provider,
            "messageCount": len(messages),
            "inputCharacters": sum(len(message["content"]) for message in messages),
            **adapter.call_metadata(),
        }
        if context:
            fields.update(workspaceId=context.workspace_id, runId=context.run_id, role=role.value if isinstance(role, AgentRole) else role)
        started = perf_counter()
        await self._records.write({**fields, "event": AICallEvent.STARTED})
        try:
            async with asyncio.timeout(adapter.timeout_seconds):
                options = {"tools": tools} if tools else {}
                result = await adapter.complete(messages, system_instruction=system_instruction, **options)
        except asyncio.CancelledError:
            await self._records.write({**fields, "event": AICallEvent.CANCELLED, "durationMs": round((perf_counter() - started) * 1000, 2)})
            raise
        except Exception as original:
            error = _public_error(original, provider)
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
        safe = {key: error.metadata[key] for key in ("providerStatus", "providerErrorType", "providerMs", "adapterMs",
                "rateLimitLimit", "rateLimitUsed", "rateLimitRequested") if key in error.metadata}
        await self._records.write({**fields, "event": AICallEvent.FAILED, "status": error.status,
                                  "errorCode": error.code, "durationMs": round((perf_counter() - started) * 1000, 2), **safe})


def _public_error(error: Exception, provider: str) -> LLMError:
    """Keep provider errors; turn unexpected failures into safe API errors."""
    if isinstance(error, LLMError):
        return error
    if isinstance(error, TimeoutError):
        return LLMError(504, f"{provider.upper()}_TIMEOUT", f"{provider.capitalize()} took too long to respond. Please try again.")
    return LLMError(502, "LLM_UNAVAILABLE", "The AI service could not complete this request. Please try again.")
