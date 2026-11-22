"""LangChain agent loops backed by the application's instrumented model gateway."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from ai_coder.mcp.client import AgentMCPClient
from ai_coder.models import AgentRole, RunContext


class GatewayModel(BaseChatModel):
    gateway: Any = Field(exclude=True)
    storage: Any = Field(default=None, exclude=True)
    context: RunContext | None = None
    role: AgentRole | Literal["coordinator"] | None = None
    request_id: str | None = None

    @property
    def _llm_type(self):
        return "ai-coder-gateway"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(tool)["function"] for tool in tools])

    def _generate(self, *args, **kwargs):
        raise NotImplementedError("Use the async model interface.")

    async def _agenerate(self, messages, stop=None, run_manager=None, tools=None, **kwargs):
        instructions, history = [], []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                instructions.append(msg.text)
                continue
            item = {"role": "user", "content": msg.text}
            if isinstance(msg, AIMessage):
                item["role"] = "assistant"
                if "providerContent" in msg.additional_kwargs:
                    item["providerContent"] = msg.additional_kwargs["providerContent"]
            elif isinstance(msg, ToolMessage):
                item.update(role="tool", name=msg.name, toolCallId=msg.tool_call_id)
            history.append(item)
        response = await self.gateway.complete(
            history,
            system_instruction="\n".join(instructions),
            context=self.context,
            role=self.role,
            request_id=self.request_id,
            tools=tools,
        )
        usage = response["usage"]
        if self.storage is not None and self.context is not None:
            self.storage.add_usage(
                self.context,
                input_tokens=usage["inputTokens"] or 0,
                output_tokens=usage["outputTokens"] or 0,
                total_tokens=usage["totalTokens"],
            )
        ai = AIMessage(
            content=response["message"]["content"],
            tool_calls=response.get("toolCalls", []),
            additional_kwargs={k: response[k] for k in ("providerContent",) if k in response},
            response_metadata={k: response[k] for k in ("model", "resolvedModel", "usage", "timing")},
        )
        return ChatResult(generations=[ChatGeneration(message=ai)])


async def invoke(model, prompt, messages, tools, timeout):
    agent = create_agent(model=model, tools=tools, system_prompt=prompt)
    async with asyncio.timeout(timeout):
        state = await agent.ainvoke({"messages": messages}, {"recursion_limit": 36})
    return state["messages"]


@asynccontextmanager
async def file_tools(settings, context, role, storage, *, written_paths=None):
    allowed = {"listFiles", "readFile"}
    if written_paths is not None:
        allowed.add("writeFile")
    async with AgentMCPClient(settings.workspaces_root, context, role) as client:

        def adapt(spec):
            async def execute(**arguments):
                storage.append_event(context, "tool_call", f"{role.value} → {spec.name}", role=role)
                result = await client.call_tool(spec.name, arguments)
                if result.is_error:
                    return f"Tool error: {result.text}"
                if spec.name == "writeFile":
                    written_paths.append(arguments["path"])
                return result.text

            return StructuredTool.from_function(
                name=spec.name,
                description=spec.description,
                args_schema=spec.input_schema,
                coroutine=execute,
            )

        yield [adapt(spec) for spec in await client.list_tools() if spec.name in allowed]
