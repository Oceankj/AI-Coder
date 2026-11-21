"""Basic chat, independent of generation runs and MCP."""
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from ai_coder.api.errors import ApiError
from ai_coder.llm.gateway import LLMError

router = APIRouter(prefix="/api/chat")

CHAT_SYSTEM_PROMPT = (
    "You are AI Coder, a helpful software planning and coding assistant. "
    "Reply in the user's language. You can discuss ideas and provide code as text. "
    "You have no tools, MCP connection, filesystem access, or ability to execute code. "
    "Never claim to have changed files or run tests. Do not request API keys in chat; "
    "the application has a separate API key form."
)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    apiKey: SecretStr

    @field_validator("apiKey")
    @classmethod
    def valid_key(cls, value):
        key = value.get_secret_value().strip()
        if not key or len(key) > 512 or any(char.isspace() for char in key):
            raise ValueError("Enter a non-empty Gemini API key without spaces.")
        return SecretStr(key)


def configuration(request: Request):
    adapter = request.app.state.llm
    return {"configured": adapter.configured, "model": adapter.model}


@router.get("/config")
async def get_config(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return configuration(request)


@router.post("/config")
async def set_config(body: KeyInput, request: Request, response: Response):
    request.app.state.llm.set_api_key(body.apiKey.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return configuration(request)


@router.post("")
async def chat(body: ChatInput, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await request.app.state.llm.complete(
            [message.model_dump() for message in body.messages],
            system_instruction=CHAT_SYSTEM_PROMPT,
            request_id=getattr(request.state, "request_id", None),
        )
        return result
    except LLMError as error:
        request.state.chat_error_code = error.code
        raise ApiError(error.status, error.code, str(error)) from None
