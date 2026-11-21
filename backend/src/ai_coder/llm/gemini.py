"""Gemini-specific SDK conversion; called only through LLMGateway."""
from __future__ import annotations

import asyncio
from time import perf_counter

from google import genai
from google.genai import errors, types

from ai_coder.llm.errors import LLMError

class GeminiAdapter:
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

    async def complete(self, messages: list[dict[str, str]], *, system_instruction: str) -> dict:
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
                    contents=[types.Content(
                        role="model" if message["role"] == "assistant" else "user",
                        parts=[types.Part(text=message["content"])],
                    ) for message in messages],
                    config=types.GenerateContentConfig(system_instruction=system_instruction),
                )
                provider_ms = round((perf_counter() - provider_started) * 1000, 2)
        except (TimeoutError, asyncio.TimeoutError):
            raise LLMError(504, "GEMINI_TIMEOUT", "Gemini took too long to respond. Please try again.", metadata=metadata()) from None
        except errors.APIError as error:
            # Provider errors may contain secrets or prompts; never expose them.
            if error.code in (401, 403) or (error.code == 400 and "API_KEY_INVALID" in str(error)):
                raise LLMError(401, "GEMINI_KEY_INVALID", "Gemini rejected this API key. Check or replace it in settings.", metadata=metadata(error.code)) from None
            if error.code == 429:
                raise LLMError(429, "GEMINI_RATE_LIMIT", "Gemini's quota or rate limit was reached. Check your quota and try again later.", metadata=metadata(error.code)) from None
            if error.code == 404:
                raise LLMError(502, "GEMINI_MODEL_NOT_FOUND", "The configured Gemini model is not available for this key. Check GEMINI_MODEL in the backend settings.", metadata=metadata(error.code)) from None
            raise LLMError(502, "GEMINI_UNAVAILABLE", "Gemini could not complete this request. Check the configured model or try again later.", metadata=metadata(error.code)) from None
        except Exception:
            raise LLMError(502, "GEMINI_UNAVAILABLE", "Could not reach Gemini. Please try again.", metadata=metadata()) from None
        text = response.text
        if not text or not text.strip():
            raise LLMError(502, "GEMINI_EMPTY_REPLY", "Gemini returned no text. Try rephrasing your message.", metadata=metadata(200))
        usage = response.usage_metadata
        return {
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
