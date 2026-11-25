# Author: Ching Kao
# Student ID: 85768427
"""LangChain agent loops backed by the application's instrumented model gateway."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from ai_coder.config import Provider
from ai_coder.mcp.client import AgentMCPClient
from ai_coder.models import AgentRole, RunContext

MAX_AGENT_MODEL_CALLS = 10
MAX_AGENT_TOOL_CALLS = 12
MAX_CONSECUTIVE_TOOL_ERRORS = 3
AGENT_GRAPH_RECURSION_LIMIT = 2 * MAX_AGENT_MODEL_CALLS + 4


class AgentBudgetExceeded(RuntimeError):
    """One agent used its bounded model or tool allowance."""


class AgentBudget:
    def __init__(self):
        self.model_calls = 0
        self.tool_calls = 0
        self.consecutive_tool_errors = 0
        self._stop_reason: str | None = None

    def defer_stop(self, error: AgentBudgetExceeded) -> None:
        if self._stop_reason is None:
            self._stop_reason = str(error)

    def check_stopped(self) -> None:
        if self._stop_reason is not None:
            raise AgentBudgetExceeded(self._stop_reason)

    def use_model(self):
        self.check_stopped()
        if self.model_calls >= MAX_AGENT_MODEL_CALLS:
            raise AgentBudgetExceeded(f"Agent exceeded {MAX_AGENT_MODEL_CALLS} model calls in one step.")
        self.model_calls += 1

    def use_tool(self):
        self.check_stopped()
        if self.tool_calls >= MAX_AGENT_TOOL_CALLS:
            raise AgentBudgetExceeded(f"Agent exceeded {MAX_AGENT_TOOL_CALLS} tool calls in one step.")
        self.tool_calls += 1

    def tool_result(self, name: str, *, failed: bool):
        self.consecutive_tool_errors = self.consecutive_tool_errors + 1 if failed else 0
        if self.consecutive_tool_errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
            raise AgentBudgetExceeded(
                f"Tool calls failed {MAX_CONSECUTIVE_TOOL_ERRORS} times without a successful tool call "
                f"(last: {name}). "
                "Check the tool result before trying again."
            )


class GatewayModel(BaseChatModel):
    gateway: Any = Field(exclude=True)
    budget: Any = Field(default_factory=AgentBudget, exclude=True)
    provider: Provider
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
        self.budget.use_model()
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
            provider=self.provider,
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
    @wrap_tool_call
    async def settle_tool_batch(request, handler):
        try:
            return await handler(request)
        except AgentBudgetExceeded as error:
            # Let admitted siblings finish and record their results before stopping.
            model.budget.defer_stop(error)
            return ToolMessage(
                content=f"Tool error: {error}",
                tool_call_id=request.tool_call["id"], name=request.tool_call["name"], status="error",
            )

    agent = create_agent(model=model, tools=tools, system_prompt=prompt, middleware=[settle_tool_batch])
    async with asyncio.timeout(timeout):
        state = await agent.ainvoke(
            {"messages": messages}, {"recursion_limit": AGENT_GRAPH_RECURSION_LIMIT}
        )
    model.budget.check_stopped()  # Also catches batches that end via a return-direct tool.
    return state["messages"]


@asynccontextmanager
async def file_tools(settings, context, role, storage, *, written_paths=None,
                     enabled=True, budget=None, write_only=None):
    if not enabled or role == AgentRole.PLANNER:
        yield []
        return
    allowed = {"listFiles", "readFile"}
    if written_paths is not None:
        allowed.add("writeFile")
    budget = budget or AgentBudget()
    async with AgentMCPClient(settings.workspaces_root, context, role) as client:

        def adapt(spec):
            async def execute(**arguments):
                budget.use_tool()
                storage.append_event(context, "tool_call", f"{role.value} → {spec.name}", role=role)
                if (spec.name == "writeFile" and write_only is not None
                        and arguments.get("path") not in write_only):
                    storage.append_event(context, "tool_result", f"{role.value} → writeFile: failed", role=role)
                    budget.tool_result(spec.name, failed=True)
                    return "Tool error: This step may write only package.json."
                try:
                    result = await client.call_tool(spec.name, arguments)
                except Exception:
                    storage.append_event(context, "tool_result", f"{role.value} → {spec.name}: failed", role=role)
                    budget.tool_result(spec.name, failed=True)
                    raise
                storage.append_event(
                    context, "tool_result",
                    f"{role.value} → {spec.name}: {'failed' if result.is_error else 'completed'}",
                    role=role,
                )
                if result.is_error:
                    budget.tool_result(spec.name, failed=True)
                    return f"Tool error: {result.text}"
                budget.tool_result(spec.name, failed=False)
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
