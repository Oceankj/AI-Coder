# Author: Ching Kao
# Student ID: 85768427
"""Gemini-specific SDK conversion; called only through LLMGateway."""
from __future__ import annotations

from uuid import uuid4
from time import perf_counter

from google import genai
from google.genai import errors, types

from ai_coder.config import Provider
from ai_coder.llm.errors import LLMError

class GeminiAdapter:
    name = Provider.GEMINI

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float):
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def set_api_key(self, api_key: str) -> None:
        # App-local, single-user configuration. Never written to disk or returned.
        self._api_key = api_key

    async def complete(self, messages: list[dict], *, system_instruction: str, tools: list[dict] | None = None) -> dict:
        started = perf_counter()
        provider_started = None
        def metadata(provider_status=None):
            return {
                "adapterMs": round((perf_counter() - started) * 1000, 2),
                "providerMs": round((perf_counter() - provider_started) * 1000, 2) if provider_started is not None else None,
                "providerStatus": provider_status,
            }
        try:
            async with genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ).aio as client:
                provider_started = perf_counter()
                response = await client.models.generate_content(
                    model=self.model,
                    contents=_contents(messages),
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        tools=[types.Tool(function_declarations=[
                            types.FunctionDeclaration(name=t["name"], description=t["description"],
                                                      parameters_json_schema=t["parameters"]) for t in tools
                        ])] if tools else None,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                provider_ms = round((perf_counter() - provider_started) * 1000, 2)
        except Exception as error:
            provider_status = error.code if isinstance(error, errors.APIError) else None
            raise _provider_error(error, metadata(provider_status)) from None
        parts = response.candidates[0].content.parts or [] if response.candidates and response.candidates[0].content else []
        text = "".join(part.text for part in parts if part.text and not part.thought)
        calls = [{"name": part.function_call.name, "args": part.function_call.args or {},
                  "id": part.function_call.id or uuid4().hex} for part in parts if part.function_call]
        if not text.strip() and not calls:
            raise LLMError(502, "GEMINI_EMPTY_REPLY", "Gemini returned no text. Try rephrasing your message.", metadata=metadata(200))
        usage = response.usage_metadata
        return {
            **({"toolCalls": calls, "providerContent": response.candidates[0].content.model_dump(mode="json", exclude_none=True)} if calls else {}),
            "message": {"role": "assistant", "content": text},
            "model": self.model,
            "resolvedModel": response.model_version or self.model,
            "timing": {"providerMs": provider_ms, "adapterMs": round((perf_counter() - started) * 1000, 2)},
            "usage": {
                "apiCalls": 1,
                "inputTokens": getattr(usage, "prompt_token_count", None),
                "outputTokens": getattr(usage, "candidates_token_count", None),
                "totalTokens": getattr(usage, "total_token_count", None),
            },
        }


def _provider_error(error: Exception, metadata: dict) -> LLMError:
    """Translate Google failures without exposing provider text or request data."""
    if isinstance(error, TimeoutError):
        return LLMError(
            504, "GEMINI_TIMEOUT", "Gemini took too long to respond. Please try again.", metadata=metadata
        )
    if isinstance(error, errors.APIError):
        if error.code in (401, 403) or (error.code == 400 and "API_KEY_INVALID" in str(error)):
            return LLMError(
                401, "GEMINI_KEY_INVALID", "Gemini rejected this API key. Check or replace it in settings.",
                metadata=metadata,
            )
        if error.code == 429:
            return LLMError(
                429, "GEMINI_RATE_LIMIT", "Gemini's quota or rate limit was reached. Check your quota and try again later.",
                metadata=metadata,
            )
        if error.code == 404:
            return LLMError(
                502, "GEMINI_MODEL_NOT_FOUND",
                "The configured Gemini model is not available for this key. Check GEMINI_MODEL in the backend settings.",
                metadata=metadata,
            )
        return LLMError(
            502, "GEMINI_UNAVAILABLE",
            "Gemini could not complete this request. Check the configured model or try again later.",
            metadata=metadata,
        )
    return LLMError(
        502, "GEMINI_UNAVAILABLE", "Could not reach Gemini. Please try again.", metadata=metadata
    )


def _contents(messages):
    contents = []
    native_ids = set()
    for message in messages:
        if "providerContent" in message:
            # Replay Google's original parts, including thought signatures.
            original = types.Content.model_validate(message["providerContent"])
            contents.append(original)
            native_ids = {p.function_call.id for p in original.parts if p.function_call and p.function_call.id}
        elif message["role"] == "tool":
            part = types.Part.from_function_response(name=message["name"], response={"result": message["content"]})
            if message.get("toolCallId") in native_ids:
                part.function_response.id = message["toolCallId"]
            if contents and contents[-1].parts and contents[-1].parts[0].function_response:
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
        else:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=message["content"])]))
    return contents
