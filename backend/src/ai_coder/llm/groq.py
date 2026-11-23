# Author: Ching Kao
# Student ID: 85768427
"""Groq chat completions behind the shared LLM gateway."""

import asyncio
import json
import re
from time import perf_counter

import httpx

from ai_coder.config import Provider
from ai_coder.llm.errors import LLMError

MAX_RATE_LIMIT_RETRIES = 2
MAX_INVALID_TOOL_CALL_RETRIES = 1
GPT_OSS_COMPLETION_TOKENS = 4096


class GroqAdapter:
    name = Provider.GROQ

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float):
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    async def complete(
        self, messages: list[dict], *, system_instruction: str, tools: list[dict] | None = None
    ) -> dict:
        started = perf_counter()
        history = [{"role": "system", "content": system_instruction}]
        history.extend(_chat_message(message) for message in messages)
        payload = {"model": self.model, "messages": history}
        if self.model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            # The provider's default completion cap can be consumed entirely by
            # reasoning, leaving an empty reply before the model writes a tool call.
            payload.update(reasoning_effort="low", max_completion_tokens=GPT_OSS_COMPLETION_TOKENS)
        elif self.model == "qwen/qwen3.8-27b":
            payload.update(reasoning_effort="none", reasoning_format="hidden", max_completion_tokens=4096)
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
            # Groq's default sampling repeatedly produced malformed tool-call JSON
            # for the Planner. Lower sampling kept the same request valid.
            payload["temperature"] = 0.2

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            sent = perf_counter()
            api_calls = 0
            invalid_tool_call_retries = 0
            rate_limit_retries = 0
            try:
                while True:
                    api_calls += 1
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=payload,
                    )
                    if (tools and invalid_tool_call_retries < MAX_INVALID_TOOL_CALL_RETRIES
                            and _tool_use_failed(response)):
                        payload = {**payload, "temperature": 0.1}
                        invalid_tool_call_retries += 1
                        continue
                    delay = _rate_limit_delay(response)
                    if rate_limit_retries < MAX_RATE_LIMIT_RETRIES and delay is not None:
                        rate_limit_retries += 1
                        await asyncio.sleep(delay)
                        continue
                    break
            except httpx.TimeoutException:
                raise LLMError(504, "GROQ_TIMEOUT", "Groq timed out. Please try again.") from None
            except httpx.RequestError:
                raise LLMError(502, "GROQ_UNAVAILABLE", "Could not reach Groq.") from None
            provider_ms = round((perf_counter() - sent) * 1000, 2)
        timing = {"providerMs": provider_ms, "adapterMs": round((perf_counter() - started) * 1000, 2)}
        metadata = {**timing, "providerStatus": response.status_code}
        if not response.is_success:
            raise _provider_error(response, metadata)
        try:
            result = _completion(response.json(), self.model)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise LLMError(502, "GROQ_INVALID_REPLY", "Groq returned an unreadable response.", metadata=metadata) from None
        if not result["message"]["content"].strip() and not result.get("toolCalls"):
            raise LLMError(502, "GROQ_EMPTY_REPLY", "Groq returned no text or tool calls.", metadata=metadata)
        result["usage"]["apiCalls"] = api_calls
        return {**result, "timing": timing}


def _tool_use_failed(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        error = response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(error, dict) and (
        error.get("code") == "tool_use_failed" or error.get("failed_generation") is not None
    )


def _rate_limit_delay(response: httpx.Response) -> float | None:
    if response.status_code != 429:
        return None
    value = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset-tokens")
    if not value:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s?", value)
    if not match:
        return None
    delay = float(match.group(1)) + 0.25
    return delay if delay <= 45 else None


def _chat_message(message: dict) -> dict:
    if message["role"] == "tool":
        return {"role": "tool", "tool_call_id": message["toolCallId"], "content": message["content"]}
    if "providerContent" in message:
        return message["providerContent"]
    return {"role": message["role"], "content": message["content"]}


def _completion(data: dict, model: str) -> dict:
    message = data["choices"][0]["message"]
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("Invalid message content")
    usage = data.get("usage") or {}
    result = {
        "message": {"role": "assistant", "content": content or ""},
        "model": model,
        "resolvedModel": data.get("model") or model,
        "usage": {
            "apiCalls": 1,
            "inputTokens": usage.get("prompt_tokens"),
            "outputTokens": usage.get("completion_tokens"),
            "totalTokens": usage.get("total_tokens"),
        },
    }
    if message.get("tool_calls"):
        calls = []
        for call in message["tool_calls"]:
            function = call["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict) or not isinstance(call["id"], str) or not isinstance(function["name"], str):
                raise ValueError("Invalid tool call")
            calls.append({"name": function["name"], "id": call["id"], "args": arguments})
        result["toolCalls"] = calls
        result["providerContent"] = {"role": "assistant", "content": content, "tool_calls": message["tool_calls"]}
    return result


def _provider_error(response: httpx.Response, metadata: dict) -> LLMError:
    status = response.status_code
    if status == 429:
        try:
            message = response.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        # Keep a closed diagnostic vocabulary; never persist the raw provider body.
        dimension = next((name for name in ("tokens per day", "tokens per minute", "requests per day", "requests per minute")
                          if name in str(message).lower()), "rate limit")
        metadata = {**metadata, "providerErrorType": dimension.replace(" ", "_")}
        for label in ("Limit", "Used", "Requested"):
            match = re.search(rf"\b{label}\s+(\d+)", str(message))
            if match:
                metadata[f"rateLimit{label}"] = int(match.group(1))
    if status == 400:
        try:
            error = response.json()["error"]
        except (ValueError, KeyError, TypeError):
            error = {}
        if _tool_use_failed(response):
            return LLMError(
                502, "GROQ_TOOL_CALL_INVALID",
                "Groq could not generate a valid tool call. Try the request again.",
                metadata={**metadata, "providerErrorType": "tool_use_failed"},
            )
        return LLMError(
            502, "GROQ_BAD_REQUEST",
            "Groq rejected the model request. Check its model and tool settings.",
            metadata={**metadata, "providerErrorType": "invalid_request"},
        )
    errors = {
        401: (401, "GROQ_KEY_INVALID", "Groq rejected the API key."),
        403: (403, "GROQ_ACCESS_DENIED", "Groq denied access to this request."),
        404: (502, "GROQ_MODEL_NOT_FOUND", "Check GROQ_MODEL and the models available to your account."),
        429: (429, "GROQ_RATE_LIMIT", "Groq's quota or rate limit was reached."),
        504: (504, "GROQ_TIMEOUT", "Groq timed out. Please try again."),
    }
    fallback = (502, "GROQ_UNAVAILABLE", "Groq could not complete this request.")
    return LLMError(*errors.get(status, fallback), metadata=metadata)
