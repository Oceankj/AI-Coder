# Author: Ching Kao
# Student ID: 85768427
"""Chat entry point. Workspace scope comes from the application."""

import json

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from ai_coder.agents.runtime import GatewayModel, invoke
from ai_coder.models import RunContext


async def coordinate(app, body, request_id):
    workspace_id = body.workspaceId
    service = app.runs
    action = {}
    prompt = (
        "You are the AI Coder Coordinator. Reply in the user's language. "
        "Answer questions directly. Clarify ambiguous requirements. Only start a run when "
        "the user asks for implementation. Use getRun for run progress. Use resumeRun for "
        "clarification on an existing blocked run. Never claim an action without its tool result."
    )
    tools = []
    if workspace_id:

        @tool("startRun", return_direct=True)
        async def start_run(description: str, requirements: list[str]) -> str:
            """Start development in this workspace. Continue from the selected stopped run's files when available."""
            if not description.strip():
                return "A description is required."
            if not action:
                run = service.start(workspace_id, description.strip(), requirements, provider=body.provider)
                action.update(runId=run.id, status=run.status)
            return f"Queued development run {action['runId']}."

        @tool("getRun")
        async def get_run(run_id: str = "") -> dict:
            """Read a run's current result, or get the latest run when the ID is omitted."""
            selected = run_id or body.runId
            if selected:
                run = service.storage.get_run(workspace_id, selected)
            else:
                latest = service.storage.list_runs(workspace_id)
                run = latest[0] if latest else None
            if not run:
                return {"message": "No matching run in this workspace."}
            return {
                "runId": run.id,
                "status": run.status,
                "role": run.active_role,
                "checks": run.checks.to_json(),
                "reason": run.error,
                "report": run.coordinator_report,
            }

        @tool("resumeRun", return_direct=True)
        async def resume_run(clarification: str, run_id: str = "") -> str:
            """Resume a blocked run with the user's clarification, keeping its run ID."""
            selected = run_id or body.runId
            if not selected or not clarification.strip():
                return "A blocked run ID and clarification are required."
            if not action:
                try:
                    run = service.resume(RunContext(workspace_id, selected), clarification)
                except ValueError as error:
                    return str(error)
                action.update(runId=run.id, status=run.status)
            return f"Resumed development run {action['runId']}."

        tools = [start_run, get_run, resume_run]
        if body.runId:
            prompt += f" Current run: {body.runId}."
    else:
        prompt += " You have no tools until a workspace is selected. For development requests ask the user to select or create a workspace."
    history = await invoke(
        GatewayModel(gateway=app.llm, provider=body.provider, request_id=request_id),
        prompt,
        [(m.role, m.content) for m in body.messages],
        tools,
        app.settings.agent_timeout_seconds,
    )
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
    except (LLMError, TimeoutError):
        return evidence["summary"]
