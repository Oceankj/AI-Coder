# Author: Ching Kao
# Student ID: 85768427
"""Chat entry point and local provider configuration."""
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from ai_coder.config import GroqModel, Provider
from ai_coder.agents.coordinator import coordinate
from ai_coder.agents.runtime import AgentBudgetExceeded
from ai_coder.api.errors import ApiError, not_found
from ai_coder.llm.errors import LLMError

router = APIRouter(prefix="/api/chat")

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider = Provider.GEMINI
    workspaceId: str | None = None
    runId: str | None = None
    messages: list[ChatMessage] = Field(min_length=1, max_length=51)

    @model_validator(mode="after")
    def conversation_order(self):
        if any(message.role != ("user" if index % 2 == 0 else "assistant") for index, message in enumerate(self.messages)) or self.messages[-1].role != "user":
            raise ValueError("Messages must alternate user/assistant and end with a user message.")
        if sum(len(message.content) for message in self.messages) > 100000:
            raise ValueError("Conversation is too long. Start a new chat.")
        return self


class KeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider = Provider.GEMINI
    apiKey: SecretStr

    @field_validator("apiKey")
    @classmethod
    def valid_key(cls, value):
        key = value.get_secret_value().strip()
        if not key or len(key) > 512 or any(char.isspace() for char in key):
            raise ValueError("Enter a non-empty API key without spaces.")
        return SecretStr(key)


class GroqModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: GroqModel


@router.get("/config")
async def get_config(request: Request, response: Response, provider: Provider = Provider.GEMINI):
    response.headers["Cache-Control"] = "no-store"
    if provider == Provider.CODEX:
        return await request.app.state.llm.codex_configuration()
    return request.app.state.llm.configuration(provider)


@router.post("/config")
async def set_config(body: KeyInput, request: Request, response: Response):
    llm = request.app.state.llm
    try:
        llm.set_api_key(body.provider, body.apiKey.get_secret_value())
    except LLMError as error:
        raise ApiError(error.status, error.code, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return llm.configuration(body.provider)


@router.post("/model")
async def set_groq_model(body: GroqModelInput, request: Request, response: Response):
    llm = request.app.state.llm
    llm.set_groq_model(body.model)
    response.headers["Cache-Control"] = "no-store"
    return llm.configuration(Provider.GROQ)


@router.post("")
async def chat(body: ChatInput, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        if body.workspaceId and request.app.state.storage.get_workspace(body.workspaceId) is None:
            raise not_found()
        if body.runId and (not body.workspaceId or request.app.state.storage.get_run(body.workspaceId, body.runId) is None):
            raise not_found()
        return await coordinate(request.app.state, body, getattr(request.state, "request_id", None))
    except LLMError as error:
        request.state.chat_error_code = error.code
        raise ApiError(error.status, error.code, str(error)) from None
    except AgentBudgetExceeded as error:
        request.state.chat_error_code = "AGENT_STEP_LIMIT"
        raise ApiError(503, "AGENT_STEP_LIMIT", str(error)) from None
