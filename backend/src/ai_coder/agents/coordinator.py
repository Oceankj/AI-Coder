# Author: Ching Kao
# Student ID: 85768427
"""Chat entry point. Workspace scope comes from the application."""

import asyncio
import json

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from ai_coder.agents.runtime import AgentBudgetExceeded, GatewayModel, invoke
from ai_coder.models import RunContext


async def coordinate(app, body, request_id):
    workspace_id = body.workspaceId
    service = app.runs
    model = GatewayModel(gateway=app.llm, provider=body.provider, request_id=request_id)
    action = {}
    prompt = (
        "You are the AI Coder Coordinator, acting as project manager. Reply in the user's language. "
        "Answer questions directly. Clarify ambiguous requirements. Only start a run when "
        "the user asks for implementation. Call getRun before explaining a run failure or its "
        "workspace files. An npm failure alone does not mean package.json is missing; use the "
        "packageJsonExists result instead of guessing. When the user asks to retry a blocked run, "
        "call resumeRun with that instruction. Keep the user's requirements, including their chosen "
        "test runner. The Architect owns technical acceptance. Never claim an action without its "
        "tool result."
    )
    tools = []
    if workspace_id:

        def selected_run(run_id: str):
            selected = run_id or body.runId
            if selected:
                return service.storage.get_run(workspace_id, selected)
            latest = service.storage.list_runs(workspace_id)
            return latest[0] if latest else None

        @tool("startRun", return_direct=True)
        async def start_run(description: str, requirements: list[str]) -> str:
            """Start development in this workspace. Continue from the selected stopped run's files when available."""
            model.budget.use_tool()
            if not description.strip():
                return "A description is required."
            if not action:
                originals = [message.content for message in body.messages if message.role == "user"]
                requirements = [*requirements, "Original user messages (latest clarification takes precedence):\n"
                                + "\n\n".join(originals)]
                run = service.start(workspace_id, description.strip(), requirements, provider=body.provider)
                action.update(runId=run.id, status=run.status)
            return f"Queued development run {action['runId']}."

        @tool("getRun")
        async def get_run(run_id: str = "") -> dict:
            """Read a run's status, failure, and actual project manifest presence."""
            model.budget.use_tool()
            run = selected_run(run_id)
            if not run:
                return {"message": "No matching run in this workspace."}
            return {
                "runId": run.id,
                "status": run.status,
                "role": run.active_role,
                "checks": run.checks.to_json(),
                "reason": run.error,
                "report": run.coordinator_report,
                "packageJsonExists": (
                    service.storage.project_dir(RunContext(workspace_id, run.id)) / "package.json"
                ).is_file(),
            }

        @tool("resumeRun", return_direct=True)
        async def resume_run(clarification: str, run_id: str = "") -> str:
            """Retry a blocked run using the user's instruction, keeping its run ID and project files."""
            model.budget.use_tool()
            run = selected_run(run_id)
            if not run or not clarification.strip():
                return "A blocked run and instruction are required."
            if not action:
                try:
                    run = service.resume(RunContext(workspace_id, run.id), clarification)
                except ValueError as error:
                    return str(error)
                action.update(runId=run.id, status=run.status)
            return f"Resumed development run {action['runId']}."

        tools = [start_run, get_run, resume_run]
        if body.runId:
            prompt += f" Current run: {body.runId}."
    else:
        prompt += " You have no tools until a workspace is selected. For development requests ask the user to select or create a workspace."
    try:
        history = await invoke(
            model,
            prompt,
            [(m.role, m.content) for m in body.messages],
            tools,
            app.settings.agent_timeout_seconds,
        )
    except asyncio.CancelledError:
        if workspace_id and action.get("runId"):
            await service.stop(RunContext(workspace_id, action["runId"]))
        raise
    replies = [m for m in history if isinstance(m, AIMessage) and "usage" in m.response_metadata]
    metadata = dict(replies[-1].response_metadata)
    usage = [m.response_metadata["usage"] for m in replies]
    metadata["usage"] = {
        k: sum(v[k] for v in usage) if all(v[k] is not None for v in usage) else None for k in usage[0]
    }
    return {
        **{k: metadata[k] for k in ("usage", "model", "resolvedModel", "timing")},
        "message": {"role": "assistant", "content": history[-1].text},
        **action,
    }


async def report_result(model, status, evidence, timeout):
    """Summarize a recorded verdict. A reporting outage cannot change the verdict."""
    from ai_coder.llm.errors import LLMError

    prompt = (
        "Coordinator report. Briefly report the recorded run outcome in the user's language. "
        "For a blocker, state what information or action is needed. Preserve the recorded verdict."
    )
    try:
        messages = await invoke(
            model, prompt, [("user", json.dumps({"status": status, **evidence}))], [], timeout
        )
        return messages[-1].text.strip() or evidence["summary"]
    except (LLMError, AgentBudgetExceeded, TimeoutError):
        return evidence["summary"]
