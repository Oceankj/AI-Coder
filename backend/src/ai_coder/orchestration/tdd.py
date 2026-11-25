# Author: Ching Kao
# Student ID: 85768427
"""Feature-by-feature LangGraph workflow. The runner owns check outcomes."""

import asyncio
import json
import inspect
import re
from pathlib import Path
from typing import Literal, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ai_coder.config import Provider
from ai_coder.agents.coder import implement, workspace_context
from ai_coder.agents.architect import design_environment
from ai_coder.agents.coordinator import diagnose_repair, report_result
from ai_coder.agents.planner import Plan, specify
from ai_coder.agents.runtime import AgentBudgetExceeded, GatewayModel, file_tools, invoke
from ai_coder.agents.tester import Assessment, Decision, assess_execution, write_cases
from ai_coder.llm.errors import LLMError
from ai_coder.mcp.tools.files import FileTools
from ai_coder.mcp.tools.scope import ToolScope
from ai_coder.models import RUN_STOP_REQUESTED, AgentRole, TaskFeature
from ai_coder.workspaces.checks import BROWSER_FAILURE, TestRunnerError, run_checks, test_path_failure, test_runner_for_project, test_setup_failure
from ai_coder.workspaces.environment import (
    EnvironmentError, environment_initialized, mark_environment_initialized,
    missing_npm_package, prepare_environment,
)
from ai_coder.workspaces.permissions import is_test_file
from ai_coder.workspaces.service import InvalidPathError, resolve_project_path
from ai_coder.workspaces.verifier import ProjectVerifierError


Route = Literal["tests", "code", "advance", "pause", "environment", "environment_fix", "architecture", "plan", "red", "green"]
Phase = Literal["Red", "Green"]
# Each feature or repair may visit several graph nodes; leave room for routing and reporting.
GRAPH_STEPS_PER_FEATURE_OR_REPAIR = 12


def check_evidence(log: str, limit: int = 4000) -> str:
    """Keep short failure messages for each reported TAP subtest in agent prompts."""
    if len(log) <= limit:
        return log
    failures = []
    for match in re.finditer(r"(?m)^not ok .+$", log):
        heading = match.group()
        block = log[match.end():].split("  ...", 1)[0]
        lines = []
        for field in ("error", "code", "actual", "expected", "location"):
            detail = re.search(rf"(?m)^  {field}:.*", block)
            if detail:
                lines.append(detail.group()[:240])
                value = detail.group().partition(":")[2].strip()
                if field in {"error", "actual", "expected"} and (
                    not value or re.fullmatch(r"[|>][+-]?", value)
                ):
                    for continuation in block[detail.end():].splitlines()[1:4]:
                        if not continuation.startswith("    "):
                            break
                        lines.append(continuation[:180])
        frames = re.search(r"(?m)^  stack:[^\n]*\n((?:    [^\n]*(?:\n|$))+)", block)
        stack = re.search(r"(?mi)^    [^\n]*\.test\.js:\d+[^\n]*", frames.group(1)) if frames else None
        if not stack:
            stack = re.search(r"(?m)^    at (?!node:).+", block)
        if stack:
            lines.append(stack.group()[:260])
        failures.append("\n".join([heading[:200], *lines]))
    if not failures:
        return log[:500] + "\n…\n" + log[-(limit - 503):]
    diagnostic = re.search(r"(?m)^\[runChecks\].+$", log)
    prefix = (diagnostic.group()[:240] + "\n") if diagnostic else ""
    budget = max(130, (limit - len(prefix) - 150) // len(failures))
    details = "\n\n".join(failure[:budget] for failure in failures)
    return (prefix + "Recorded TAP failures:\n" + details)[:limit - 100] + "\n\n" + log[-90:]


def failure_signature(log: str) -> str:
    """Identify the failing checks, ignoring TAP ordinals, timing and source locations."""
    first = log.partition("\n")[0]
    if first.startswith(BROWSER_FAILURE):
        return first
    failures = set()
    for match in re.finditer(r"(?m)^not ok \d+ - (.+)$", log):
        block = log[match.end():].split("\n  ...", 1)[0]
        detail = re.search(r"(?m)^  error: *(.*?)(?:\n    (.*))?$", block)
        message = ""
        if detail:
            message = detail.group(1).strip()
            if re.fullmatch(r"[|>][+-]?", message):
                message = (detail.group(2) or "").strip()
        failures.add(f"{match.group(1)}: {message}" if message else match.group(1))
    if not failures:
        failures.update(re.findall(r"(?m)^\s*● (.+)$", log))
    return "\n".join(sorted(failures))


class State(TypedDict, total=False):
    resume_node: str
    retry_node: str
    repair_start_count: int
    spec: str
    interface_language: str | None
    features: list[dict]
    index: int
    execution: dict
    assessment: dict
    clarification: str
    route: Route
    environment: dict
    environment_result: str
    test_runner: str
    environment_error: str
    browser_failure: str
    repair_signature: str
    repair_execution: int
    repair_history: list[str]
    repair_instruction: str
    reassess_repair: bool
    test_setup_error: str
    environment_repair: bool
    environment_consulted: bool
    environment_return: str
    review_feedback: str
    review: dict


class WorkflowBlock(Exception):
    """A recoverable condition that needs user input."""


class TDDRun:
    def __init__(self, storage, gateway, settings, context):
        self.storage, self.settings, self.gateway = storage, settings, gateway
        self.ctx = context
        self.provider = self.run_record().provider
        self.checkpoint = None

    def run_record(self):
        return self.storage.get_run(self.ctx.workspace_id, self.ctx.run_id)

    def spend_repair(self, state):
        total = self.run_record().repair_count
        if total - state.get("repair_start_count", 0) >= self.settings.max_repairs:
            return False
        self.storage.update_run(self.ctx, repair_count=total + 1)
        return True

    async def run_agent(self, role, prompt, payload, *, stage, schema=None, writable=False,
                        use_file_tools=True, write_only=None):
        self.storage.update_run(self.ctx, active_role=role)
        self.storage.append_event(self.ctx, "role_started", stage, role=role)
        model = GatewayModel(gateway=self.gateway, provider=self.provider, storage=self.storage, role=role, context=self.ctx)
        self.storage.publish_task(
            self.ctx,
            role,
            prompt,
            plan=payload.get("spec"),
            feature=TaskFeature.model_validate(payload["taskFeature"])
            if "taskFeature" in payload
            else None,
            repair=(payload.get("assessment") or {}).get("decision")
            in (Decision.TEST_INVALID, Decision.IMPLEMENTATION_DEFECT),
            previous_failure=(payload.get("execution") or {}).get("log"),
        )
        written = [] if writable else None
        parser = PydanticOutputParser(pydantic_object=schema) if schema else None
        if parser:
            prompt += "\n" + parser.get_format_instructions()
        async with file_tools(
            self.settings, self.ctx, role, self.storage,
            written_paths=written,
            enabled=use_file_tools,
            budget=model.budget,
            write_only=write_only,
        ) as tools:
            try:
                timeout = self.settings.agent_timeout_seconds
                async with asyncio.timeout(timeout):
                    messages = await invoke(model, prompt, [("user", json.dumps(payload))], tools, timeout)
                    if writable and not written and any(tool.name == "writeFile" for tool in tools):
                        self.storage.append_event(
                            self.ctx, "write_retry",
                            f"{role.value} ended before writing; requesting the missing file once.", role=role,
                        )
                        correction = (
                            "user",
                            "No permitted file was written. Continue this same task using the available writeFile "
                            "tool with the actual path and complete file content. Confirm the tool succeeded "
                            "before ending. Text or code blocks in the reply do not save a file.",
                        )
                        messages = await invoke(model, prompt, [*messages, correction], tools, timeout)
                    if parser:
                        try:
                            result = parser.parse(messages[-1].text)
                        except OutputParserException:
                            self.storage.append_event(
                                self.ctx, "schema_retry",
                                f"{role.value} returned an unreadable {schema.__name__}; requesting JSON once.",
                                role=role,
                            )
                            correction = (
                                "user",
                                "The previous final reply did not match the required JSON schema above. "
                                "Return the complete JSON object with the exact fields and value types from "
                                "that schema. Reuse the prior findings. Do not repeat any completed tool "
                                "calls, add commentary, or wrap the JSON in a code fence.",
                            )
                            messages = await invoke(model, prompt, [*messages, correction], tools, timeout)
                            result = parser.parse(messages[-1].text)
                summary = messages[-1].text
            except AgentBudgetExceeded as error:
                if not (written and schema is None):
                    raise WorkflowBlock(str(error)) from error
                interruption = str(error)
            except LLMError as error:
                recoverable = {
                    Provider.GROQ: {"GROQ_RATE_LIMIT", "GROQ_TOOL_CALL_INVALID", "GROQ_TIMEOUT"},
                    Provider.CODEX: {"CODEX_RATE_LIMIT", "CODEX_INVALID_REPLY", "CODEX_TIMEOUT"},
                }
                if not (written and schema is None and error.code in recoverable.get(self.provider, ())):
                    raise
                interruption = error.code
            else:
                interruption = None
        if interruption:
            summary = f"Wrote {', '.join(written)}; checking project after interruption ({interruption})."
            self.storage.append_event(self.ctx, "agent_interrupted", summary, role=role)
        if writable and not written:
            raise WorkflowBlock(
                f"{role.value.capitalize()} finished without writing a permitted project file."
            )
        if not parser:
            result = summary
        features = (
            [{"title": f.title, "description": "\n".join(f.criteria)} for f in result.features]
            if isinstance(result, Plan)
            else []
        )
        self.storage.submit_result(
            self.ctx,
            role,
            summary=result.model_dump_json() if isinstance(result, BaseModel) else result,
            artifact_paths=written or [],
            outcome="success",
            features=features,
        )
        return result

    async def plan(self, state):
        revising = (bool(state.get("features"))
                    and state.get("index", 0) < len(state["features"])
                    and not state.get("review_feedback"))
        payload = {
            "request": self.run_record().input.to_json(),
            "clarification": state.get("clarification"),
            "existingFiles": [file.path for file in self.storage.list_project_files(self.ctx)],
            "reviewFeedback": state.get("review_feedback"),
        }
        limit = self.settings.max_features
        if revising:
            payload.update(
                feature=state["features"][state["index"]],
                previousSpec=state["spec"],
                previousAssessment=state.get("assessment"),
                execution=state.get("execution"),
            )
            limit = 1
        plan = await specify(self.run_agent, payload, limit)
        features = [f.model_dump() for f in plan.features]
        if revising:
            features = list(state["features"])
            features[state["index"]] = plan.features[0].model_dump()
        spec = state["spec"] + "\nClarification: " + plan.spec if revising else plan.spec
        return {
            "spec": spec,
            "interface_language": plan.interface_language or state.get("interface_language"),
            "features": features,
            "index": state.get("index", 0) if revising else 0,
            "assessment": {},
            "execution": {},
            "review_feedback": "",
            "environment_consulted": False,
            "environment_repair": False,
        }

    def environment_gate(self, state):
        """Reuse a prepared workspace; ask Architect only for first setup or a failure."""
        if environment_initialized(self.storage.project_dir(self.ctx)):
            self.storage.append_event(self.ctx, "environment_bypassed", "Reusing the workspace environment.")
            return {"route": "environment", "environment": {"reason": "Existing workspace environment", "packages": {}}}
        return {"route": "architecture"}

    async def architecture(self, state):
        manifest = self.storage.project_dir(self.ctx) / "package.json"
        manifest_data = None
        if manifest.is_file() and not manifest.is_symlink():
            try:
                parsed = json.loads(manifest.read_text(encoding="utf-8"))
                manifest_data = {
                    key: parsed.get(key) for key in ("type", "dependencies", "devDependencies")
                    if isinstance(parsed, dict) and key in parsed
                }
            except (OSError, UnicodeError, json.JSONDecodeError):
                manifest_data = {"error": "package.json is not readable JSON"}
        plan = await design_environment(self.run_agent, {
            "request": self.run_record().input.to_json(),
            "spec": state["spec"],
            "features": state["features"],
            "existingFiles": [file.path for file in self.storage.list_project_files(self.ctx)],
            "packageManifest": manifest_data,
            "environmentError": state.get("environment_error"),
        })
        self.storage.append_event(self.ctx, "environment_plan", plan.reason, role=AgentRole.ARCHITECT)
        return {"environment": plan.model_dump(), "environment_consulted": True,
                "environment_repair": False}

    async def environment(self, state):
        self.storage.update_run(self.ctx, active_role=None)
        packages = {} if state.get("environment_repair") else state["environment"]["packages"]
        try:
            result = await prepare_environment(self.storage.project_dir(self.ctx), packages,
                                               timeout_seconds=self.settings.setup_timeout_seconds)
            runner = test_runner_for_project(self.storage.project_dir(self.ctx))
            if state.get("environment_consulted"):
                mark_environment_initialized(self.storage.project_dir(self.ctx))
        except (EnvironmentError, TestRunnerError) as error:
            return self.environment_failure(str(error), state, repairable=getattr(error, "repairable", True))
        self.storage.append_event(self.ctx, "environment_ready", f"{result} Test runner: {runner.value}.")
        return {"route": state.get("environment_return") or "tests", "environment_result": result,
                "environment_error": "", "test_runner": runner.value, "environment_return": "", "retry_node": ""}

    def environment_failure(self, reason, state, *, repairable=True, return_to=None):
        self.storage.append_event(self.ctx, "environment_failed", reason)
        return_to = return_to or state.get("environment_return") or "tests"
        if not repairable:
            return {"route": "pause", "assessment": {"reason": reason},
                    "retry_node": "environment" if return_to == "tests" else return_to}
        if "npm was not found" in reason or not self.spend_repair(state):
            return {"route": "pause", "retry_node": "environment", "assessment": {"reason": reason}}
        if not state.get("environment_consulted"):
            return {"route": "architecture", "environment_error": reason, "environment_return": return_to}
        return {"route": "environment_fix", "environment_error": reason, "environment_return": return_to}

    async def environment_fix(self, state):
        await self.run_agent(
            AgentRole.CODER,
            "Coder environment repair. Fix only package.json dependency declarations using writeFile. "
            "Use registry packages and explicit semver versions; no install scripts or URLs. "
            "Do not edit tests or application code in this step.",
            {"spec": state["spec"], "environment": state["environment"],
             "environmentError": state["environment_error"]},
            stage="Coder environment repair", writable=True, write_only={"package.json"},
        )
        return {"environment_repair": True}

    def playlist_import_feature(self, state):
        """Select the first feature that implements the request's local folder picker."""
        if not self.settings.project_verifier:
            return None
        request = self.run_record().input
        description = " ".join([request.description, *request.requirements]).lower()
        folder = r"\bfolder\b|資料夾|文件夾"
        if not all(re.search(pattern, description) for pattern in (
            r"\bcss\b", r"\bplaylist|歌單|播放清單",
            r"\b(?:music|audio)\b|音樂|音訊|音檔", folder,
        )):
            return None
        return next((
            index for index, feature in enumerate(state["features"])
            if re.search(folder, " ".join([feature["title"], *feature.get("criteria", [])]).lower())
        ), len(state["features"]) - 1)

    def task(self, state):
        feature = state["features"][state["index"]]
        return {
            "spec": state["spec"],
            "interfaceLanguage": state.get("interface_language"),
            "feature": feature,
            "taskFeature": {
                "title": feature["title"],
                "description": "\n".join(feature["criteria"]),
                "number": state["index"] + 1,
                "total": len(state["features"]),
            },
            "execution": state.get("execution"),
            "assessment": state.get("assessment"),
            "environment": state.get("environment"),
            "testRunner": state.get("test_runner"),
            "systemChecks": (
                ["Open the styled page and select a real directory containing two synthetic songs, "
                 "including one in a subfolder. Both song titles must appear."]
                if state["index"] == self.playlist_import_feature(state) else []
            ),
            "existingTestFiles": [
                file.path for file in self.storage.list_project_files(self.ctx) if is_test_file(file.path)
            ],
            "reviewFeedback": state.get("review_feedback"),
            "repairInstruction": state.get("repair_instruction") or None,
            "clarification": state.get("clarification"),
        }

    async def tests(self, state):
        task = self.task(state)
        task["projectFiles"] = [file.path for file in self.storage.list_project_files(self.ctx)]
        await write_cases(self.run_agent, task)

    async def check(self, state, phase: Phase):
        self.storage.update_run(self.ctx, active_role=None)
        try:
            await prepare_environment(self.storage.project_dir(self.ctx), {},
                                      timeout_seconds=self.settings.setup_timeout_seconds)
            runner = test_runner_for_project(self.storage.project_dir(self.ctx))
        except (EnvironmentError, TestRunnerError) as error:
            return self.environment_failure(f"Environment setup before {phase} checks failed: {error}", state,
                                            repairable=getattr(error, "repairable", True), return_to=phase.lower())
        if runner.value != state["test_runner"]:
            raise WorkflowBlock(
                f"Test runner changed from {state['test_runner']} to {runner.value} after Tester authored the tests. "
                "Keep one runner for the current feature."
            )
        import_feature = self.playlist_import_feature(state)
        verifier = (
            self.settings.project_verifier
            if import_feature is not None and state["index"] in (import_feature, len(state["features"]) - 1)
            else None
        )
        try:
            options = {"browser_verifier": verifier} if verifier else {}
            check = await run_checks(self.storage, self.ctx, **options)
        except ProjectVerifierError as error:
            raise WorkflowBlock(str(error)) from error
        self.storage.append_event(
            self.ctx,
            "checks",
            f"Feature {state['index'] + 1} {phase}: execution {check.id}, "
            f"{check.passed} passed, {check.failed} failed ({check.outcome}).",
        )
        self.storage.update_run(self.ctx, checks={"build": "not_run", "tests": check.outcome})
        result = check.to_json()
        result["log"] = check_evidence(check.log)
        setup_error = None
        if check.outcome == "failed":
            project = self.storage.project_dir(self.ctx)
            setup_error = test_path_failure(project, check.log) or test_setup_failure(project, check.log)
        if check.outcome == "failed" and not setup_error:
            package = missing_npm_package(result["log"])
            if package:
                return {"execution": result, **self.environment_failure(
                    f"Node checks cannot resolve npm package {package}.", state, return_to=phase.lower()
                )}
        return {"execution": result, "route": phase.lower(), "retry_node": "", "test_setup_error": setup_error or ""}

    async def red(self, state):
        return await self.check(state, "Red")

    async def green(self, state):
        return await self.check(state, "Green")

    @staticmethod
    def route_assessment(assessment: Assessment, state: State, phase: Phase) -> tuple[Route, Assessment]:
        """Match the Tester's diagnosis against the recorded runner result."""
        check = state["execution"]
        decision = assessment.decision
        if decision in (Decision.BLOCKED, Decision.UNKNOWN):
            return "pause", assessment
        if decision == Decision.TEST_INVALID:
            return "tests", assessment
        if phase == "Red" and decision == Decision.IMPLEMENTATION_DEFECT:
            assessment = Assessment(decision=Decision.EXPECTED_FAILURE, reason=assessment.reason)
            decision = assessment.decision
        if phase == "Green" and decision == Decision.EXPECTED_FAILURE:
            assessment = Assessment(decision=Decision.IMPLEMENTATION_DEFECT, reason=assessment.reason)
            decision = assessment.decision
        if phase == "Red" and decision == Decision.ALREADY_PASSING and TDDRun.passed(state):
            return "advance", assessment
        if (
            decision == (Decision.EXPECTED_FAILURE if phase == "Red" else Decision.IMPLEMENTATION_DEFECT)
            and check["outcome"] == "failed"
            and not check["timedOut"]
            and check["failed"] > 0
        ):
            return "code", assessment
        return "pause", Assessment(
            decision=Decision.BLOCKED,
            reason=f"Tester diagnosis conflicts with execution {check['id']}. {assessment.reason}",
        )

    def missing_implementation(self, state):
        """Identify an absent project module without confusing it with a missing npm package."""
        log = state["execution"].get("log", "")
        missing = re.search(r"Cannot find module ['\"](\./[^'\"]+)['\"]", log)
        if not missing:
            missing = re.search(
                r"Cannot find module ['\"](/[^'\"]+\.(?:js|cjs|mjs))['\"]", log,
            )
        if not missing:
            return None
        project_root = self.storage.project_dir(self.ctx).resolve()
        missing_path = missing.group(1)
        try:
            project_path = (Path(missing_path).relative_to(project_root).as_posix()
                            if missing_path.startswith("/") else missing_path.removeprefix("./"))
            target = resolve_project_path(project_root, project_path)
        except (ValueError, InvalidPathError):
            return None
        named_modules = {name.removeprefix("./") for name in re.findall(r"[\w./-]+\.(?:js|cjs|mjs)\b", state["spec"])}
        if (not target.exists() and not is_test_file(project_path)
                and not project_path.startswith("node_modules/")
                and (not named_modules or project_path in named_modules)):
            return project_path
        return None

    async def coordinator_repair(self, state, history):
        task = self.task(state)
        files = FileTools(ToolScope(self.storage, self.ctx, AgentRole.CODER))
        task["workspaceContext"] = workspace_context(files, task)
        task["requirements"] = self.run_record().input.to_json()
        task["attemptedRepairs"] = history
        task["recentWrites"] = [
            {"role": row.role.value, "paths": row.result.artifact_paths}
            for row in self.storage.list_tasks(self.ctx)[-10:]
            if row.result and row.result.artifact_paths
        ]
        model = GatewayModel(
            gateway=self.gateway, provider=self.provider, storage=self.storage, role="coordinator", context=self.ctx,
        )
        self.storage.append_event(self.ctx, "role_started", "Coordinator repair diagnosis", role="coordinator")
        return await diagnose_repair(model, task, self.settings.agent_timeout_seconds)

    async def assess(self, state: State, phase: Phase):
        check = state["execution"]
        missing = self.missing_implementation(state) if check["outcome"] == "failed" and not check["timedOut"] else None
        syntax = re.search(r"\[runChecks\] Syntax error in (test|implementation) file: ([^\n]+)", check.get("log", ""))
        browser_failure = check.get("log", "").partition("\n")[0]
        setup_error = state.get("test_setup_error")
        signature = failure_signature(check.get("log", "")) if check["outcome"] == "failed" else ""
        same_failure = bool(signature and signature == state.get("repair_signature"))
        history = list(state.get("repair_history", [])) if same_failure else []
        instruction = ""
        from_coordinator = (
            check["outcome"] == "failed" and not check["timedOut"]
            and (state.get("reassess_repair") or (same_failure and check["id"] != state.get("repair_execution")))
        )
        if from_coordinator:
            total_repairs = self.run_record().repair_count - state.get("repair_start_count", 0)
            from_coordinator = total_repairs < self.settings.max_repairs
        if from_coordinator:
            if not history and (previous := state.get("assessment") or {}).get("reason"):
                history.append(previous["reason"])
            diagnosis = await self.coordinator_repair(state, history)
            instruction = " ".join(diagnosis.instruction.split())
            target = diagnosis.target
            if setup_error and target == "coder":
                target = "tester"
                instruction = setup_error
            if target == "pause" or not instruction or instruction.casefold() in {
                " ".join(prior.split()).casefold() for prior in history
            }:
                assessment = Assessment(decision=Decision.BLOCKED, reason=diagnosis.reason)
                instruction = ""
            else:
                assessment = Assessment(
                    decision=Decision.TEST_INVALID if target == "tester" else Decision.IMPLEMENTATION_DEFECT,
                    reason=diagnosis.reason,
                )
            self.storage.append_event(
                self.ctx, "repair_diagnosis",
                f"{target}: {assessment.reason}" + (f" Repair instruction: {instruction}" if instruction else ""),
                role="coordinator",
            )
        elif setup_error and check["outcome"] == "failed" and not check["timedOut"]:
            assessment = Assessment(decision=Decision.TEST_INVALID, reason=setup_error)
        elif browser_failure.startswith(BROWSER_FAILURE):
            assessment = Assessment(decision=Decision.IMPLEMENTATION_DEFECT, reason=browser_failure)
        elif syntax:
            assessment = Assessment(
                decision=(Decision.TEST_INVALID if syntax.group(1) == "test" else
                          Decision.EXPECTED_FAILURE if phase == "Red" else Decision.IMPLEMENTATION_DEFECT),
                reason=f"Node syntax validation failed for {syntax.group(2)} ({syntax.group(1)} file).",
            )
        elif missing:
            assessment = Assessment(
                decision=Decision.EXPECTED_FAILURE if phase == "Red" else Decision.IMPLEMENTATION_DEFECT,
                reason=f"The required implementation module {missing} has not been created.",
            )
        else:
            task = self.task(state)
            if self.passed(state) and (task["assessment"] or {}).get("decision") == Decision.TEST_INVALID:
                files = FileTools(ToolScope(self.storage, self.ctx, AgentRole.TESTER))
                task["revisedTests"] = workspace_context(files, task)["files"]
            assessment = await assess_execution(self.run_agent, task, phase)
        reported_decision = assessment.decision
        route, assessment = self.route_assessment(assessment, state, phase)
        # A failed test hook can be an incomplete test setup. Give the Tester
        # one chance to repair it; an ordinary requirement blocker still pauses.
        if (phase == "Red" and route == "pause"
                and assessment.decision == Decision.BLOCKED
                and state["execution"]["outcome"] == "failed"
                and not state["execution"]["timedOut"]
                and "failureType: 'hookFailed'" in state["execution"].get("log", "")
                and self.run_record().repair_count == 0):
            route = "tests"
        retry_node = phase.lower() if from_coordinator and route == "pause" else ""
        if route == "pause" and reported_decision not in (Decision.BLOCKED, Decision.UNKNOWN):
            retry_node = "red_review" if phase == "Red" else "diagnose"
        if (route == "tests" or (route == "code" and phase == "Green")) and not self.spend_repair(state):
            retry_node, route = route, "pause"
            assessment = assessment.model_copy(update={"reason": "Repair budget exhausted. " + assessment.reason})
        self.storage.append_event(
            self.ctx,
            "diagnosis",
            f"Execution {state['execution']['id']}: {assessment.decision.value} — {assessment.reason}",
            role=AgentRole.TESTER,
        )
        repair_scheduled = route == "tests" or (route == "code" and (phase == "Green" or from_coordinator))
        return {
            "assessment": assessment.model_dump(mode="json"), "route": route, "retry_node": retry_node,
            "browser_failure": browser_failure if browser_failure.startswith(BROWSER_FAILURE) else "",
            "repair_signature": signature if repair_scheduled else "",
            "repair_execution": check["id"],
            "repair_history": ([*history, instruction or assessment.reason] if repair_scheduled else history),
            "repair_instruction": instruction,
            "reassess_repair": False,
        }

    @staticmethod
    def passed(state):
        check = state["execution"]
        return check["outcome"] == "passed" and check["passed"] > 0

    async def red_review(self, state):
        return await self.assess(state, "Red")

    async def diagnose(self, state):
        return await self.assess(state, "Green")

    async def code(self, state):
        task = self.task(state)
        files = FileTools(ToolScope(self.storage, self.ctx, AgentRole.CODER))
        task["workspaceContext"] = workspace_context(files, task)
        await implement(self.run_agent, task)

    async def advance(self, state):
        self.storage.append_event(self.ctx, "feature_completed", state["features"][state["index"]]["title"])
        return {"index": state["index"] + 1, "assessment": {}, "execution": {},
                "repair_signature": "", "repair_history": [], "repair_instruction": ""}

    async def acceptance(self, state):
        checks = self.storage.list_check_executions(self.ctx)
        if not checks or checks[-1].outcome != "passed" or checks[-1].passed < 1:
            raise WorkflowBlock("Final acceptance requires a passing runChecks execution with at least one test.")
        check = checks[-1]
        self.storage.append_event(self.ctx, "acceptance", f"approve: runChecks execution {check.id} passed ({check.passed} tests).")
        return {"route": "advance"}

    async def report(self, status, summary):
        model = GatewayModel(
            gateway=self.gateway, provider=self.provider, storage=self.storage, context=self.ctx, role="coordinator"
        )
        evidence = {"summary": summary, "request": self.run_record().input.description}
        report = await report_result(model, status, evidence, self.settings.agent_timeout_seconds)
        self.storage.append_event(self.ctx, status, report, role="coordinator")
        return report

    async def pause(self, state, *, retry_node=None, reason=None):
        reason = reason or state["assessment"]["reason"]
        self.storage.append_event(self.ctx, "blocked", reason, role="coordinator")
        self.storage.update_run(
            self.ctx,
            status="blocked",
            active_role=None,
            error=reason,
            continuation={**state, "resume_node": retry_node or state.get("retry_node") or "plan"},
            coordinator_report=reason,
        )

    async def finish(self, state):
        self.storage.package_run(self.ctx)
        summary = f"Completed all {len(state['features'])} planned features. All required tests passed."
        report = await self.report("completed", summary)
        self.storage.update_run(
            self.ctx, status="completed", active_role=None, continuation=None, coordinator_report=report
        )

    def checkpoint_node(self, name):
        async def execute_node(state):
            # Save the input to the actual step, not the last emitted graph snapshot.
            # A provider failure can then retry this step after a process restart.
            self.checkpoint = {**state, "resume_node": name}
            self.storage.update_run(self.ctx, continuation=self.checkpoint)
            result = getattr(self, name)(state)
            return await result if inspect.isawaitable(result) else result
        return execute_node

    def build_graph(self):
        """Declare the TDD steps and their evidence-based transitions."""
        graph = StateGraph(State)
        nodes = ("plan", "environment_gate", "architecture", "environment", "environment_fix", "tests", "red", "red_review", "code", "green", "diagnose", "advance", "acceptance", "pause", "finish")
        for name in nodes:
            graph.add_node(name, self.checkpoint_node(name))
        graph.add_conditional_edges(START, lambda state: state.get("resume_node", "plan"), list(nodes))
        graph.add_edge("plan", "environment_gate")
        graph.add_conditional_edges("environment_gate", lambda s: s["route"])
        graph.add_edge("architecture", "environment")
        graph.add_conditional_edges("environment", lambda s: s["route"])
        graph.add_edge("environment_fix", "environment")
        graph.add_edge("tests", "red")
        graph.add_conditional_edges("red", lambda s: s["route"] if s["route"] in {"architecture", "environment_fix", "pause"} else "red_review")
        graph.add_conditional_edges("red_review", lambda s: s["route"])
        graph.add_edge("code", "green")
        graph.add_conditional_edges("green", lambda s: s["route"] if s["route"] in {"architecture", "environment_fix", "pause"} else ("advance" if self.passed(s) else "diagnose"))
        graph.add_conditional_edges("diagnose", lambda s: s["route"])
        graph.add_conditional_edges(
            "advance", lambda s: "tests" if s["index"] < len(s["features"]) else "acceptance"
        )
        graph.add_conditional_edges("acceptance", lambda s: "finish" if s["route"] == "advance" else s["route"])
        graph.add_edge("pause", END)
        graph.add_edge("finish", END)
        return graph.compile()

    async def execute(self):
        graph = self.build_graph()
        initial = self.run_record().continuation or {"index": 0}
        self.storage.update_run(self.ctx, status="running", error=None)
        result = initial
        graph_step_budget = self.settings.max_features + self.settings.max_repairs + 3
        config = {"recursion_limit": GRAPH_STEPS_PER_FEATURE_OR_REPAIR * graph_step_budget}
        try:
            async for snapshot in graph.astream(
                initial, config, stream_mode="values", version="v1"
            ):
                result = snapshot
            if self.run_record().status == "blocked":
                return
        except (WorkflowBlock, AgentBudgetExceeded, OutputParserException) as error:
            reason = (
                str(error)
                if isinstance(error, (WorkflowBlock, AgentBudgetExceeded))
                else "The agent returned an unreadable plan or diagnosis."
            )
            checkpoint = self.checkpoint or result
            await self.pause(checkpoint, reason=reason, retry_node=checkpoint.get("resume_node"))
        except LLMError as error:
            checkpoint = self.checkpoint or result
            await self.pause(checkpoint, reason=str(error), retry_node=checkpoint.get("resume_node"))
        except asyncio.CancelledError as error:
            if error.args != (RUN_STOP_REQUESTED,):
                self.storage.update_run(self.ctx, status="failed", error="Run interrupted.", active_role=None)
            raise
        except Exception as error:
            # Parser and tool exceptions may contain full model output.
            reason = (
                str(error)
                if isinstance(error, LLMError) or type(error) is ValueError
                else f"Workflow stopped ({type(error).__name__})."
            )
            self.storage.update_run(self.ctx, status="failed", error=reason[:500], active_role=None)
            self.storage.append_event(self.ctx, "failed", reason[:500])


class TDDWorkflow:
    def __init__(self, storage, gateway, settings):
        self.storage, self.gateway, self.settings = storage, gateway, settings

    async def run(self, context):
        await TDDRun(self.storage, self.gateway, self.settings, context).execute()
