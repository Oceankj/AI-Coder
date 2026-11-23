# Author: Ching Kao
# Student ID: 85768427
"""Feature-by-feature LangGraph workflow. The runner owns check outcomes."""

import asyncio
import json
import re
from typing import Literal, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ai_coder.config import Provider
from ai_coder.agents.coder import implement
from ai_coder.agents.architect import ReviewDecision, design_environment, review_project
from ai_coder.agents.coordinator import report_result
from ai_coder.agents.planner import Plan, specify
from ai_coder.agents.runtime import AgentBudgetExceeded, GatewayModel, file_tools, invoke
from ai_coder.agents.tester import Assessment, Decision, assess_execution, write_cases
from ai_coder.llm.errors import LLMError
from ai_coder.models import AgentRole, TaskFeature
from ai_coder.workspaces.checks import TestRunnerError, run_checks, test_runner_for_project
from ai_coder.workspaces.environment import (
    EnvironmentError, environment_initialized, mark_environment_initialized,
    missing_npm_package, prepare_environment,
)
from ai_coder.workspaces.permissions import is_test_file
from ai_coder.workspaces.service import InvalidPathError, resolve_project_path


Route = Literal["tests", "code", "advance", "pause", "environment", "environment_fix", "architecture", "plan"]
Phase = Literal["Red", "Green"]
# Each feature or repair may visit several graph nodes; leave room for routing and reporting.
GRAPH_STEPS_PER_FEATURE_OR_REPAIR = 12


class State(TypedDict, total=False):
    spec: str
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
    environment_repair: bool
    environment_consulted: bool
    review_feedback: str
    review: dict


class WorkflowBlock(Exception):
    """A recoverable condition that needs user input."""


class TDDRun:
    def __init__(self, storage, gateway, settings, context):
        self.storage, self.settings, self.gateway = storage, settings, gateway
        self.ctx = context
        self.provider = self.run_record().provider

    def run_record(self):
        return self.storage.get_run(self.ctx.workspace_id, self.ctx.run_id)

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
                messages = await invoke(
                    model, prompt, [("user", json.dumps(payload))], tools, self.settings.agent_timeout_seconds
                )
                summary = messages[-1].text
            except AgentBudgetExceeded as error:
                raise WorkflowBlock(str(error)) from error
            except LLMError as error:
                if not (writable and written and self.provider == Provider.GROQ
                        and error.code in {"GROQ_RATE_LIMIT", "GROQ_TOOL_CALL_INVALID", "GROQ_TIMEOUT"}):
                    raise
                self.storage.append_event(
                    self.ctx, "agent_interrupted",
                    f"{role.value} wrote {len(written)} file(s); checking project after {error.code}.", role=role,
                )
                summary = f"Wrote {', '.join(written)}; checking project after {error.code}."
        if writable and not written:
            raise WorkflowBlock(
                f"{role.value.capitalize()} finished without writing a permitted project file."
            )
        result = parser.parse(summary) if parser else summary
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
            return self.environment_failure(str(error), state)
        self.storage.append_event(self.ctx, "environment_ready", f"{result} Test runner: {runner.value}.")
        return {"route": "tests", "environment_result": result, "environment_error": "", "test_runner": runner.value}

    def environment_failure(self, reason, state):
        self.storage.append_event(self.ctx, "environment_failed", reason)
        used = self.run_record().repair_count
        if used >= self.settings.max_repairs or "npm was not found" in reason:
            return {"route": "pause", "assessment": {"reason": reason}}
        self.storage.update_run(self.ctx, repair_count=used + 1)
        if not state.get("environment_consulted"):
            return {"route": "architecture", "environment_error": reason}
        return {"route": "environment_fix", "environment_error": reason}

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

    def task(self, state):
        feature = state["features"][state["index"]]
        return {
            "spec": state["spec"],
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
            "existingTestFiles": [
                file.path for file in self.storage.list_project_files(self.ctx) if is_test_file(file.path)
            ],
            "reviewFeedback": state.get("review_feedback"),
        }

    async def tests(self, state):
        await write_cases(self.run_agent, self.task(state))

    async def check(self, state, phase: Phase):
        self.storage.update_run(self.ctx, active_role=None)
        try:
            await prepare_environment(self.storage.project_dir(self.ctx), {},
                                      timeout_seconds=self.settings.setup_timeout_seconds)
            runner = test_runner_for_project(self.storage.project_dir(self.ctx))
        except (EnvironmentError, TestRunnerError) as error:
            return self.environment_failure(f"Environment setup before {phase} checks failed: {error}", state)
        if runner.value != state["test_runner"]:
            raise WorkflowBlock(
                f"Test runner changed from {state['test_runner']} to {runner.value} after Tester authored the tests. "
                "Keep one runner for the current feature."
            )
        check = await run_checks(self.storage, self.ctx)
        self.storage.append_event(
            self.ctx,
            "checks",
            f"Feature {state['index'] + 1} {phase}: execution {check.id}, "
            f"{check.passed} passed, {check.failed} failed ({check.outcome}).",
        )
        self.storage.update_run(self.ctx, checks={"build": "not_run", "tests": check.outcome})
        result = check.to_json()
        result["log"] = check.log[-4000:]
        if check.outcome == "failed":
            package = missing_npm_package(result["log"])
            if package:
                return {"execution": result, **self.environment_failure(
                    f"Node checks cannot resolve npm package {package}.", state
                )}
        return {"execution": result}

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

    async def assess(self, state: State, phase: Phase):
        assessment = await assess_execution(self.run_agent, self.task(state), phase)
        if phase == "Red" and assessment.decision == Decision.TEST_INVALID:
            missing = re.search(r"Cannot find module ['\"](\./[^'\"]+)['\"]", state["execution"].get("log", ""))
            if missing:
                project_path = missing.group(1).removeprefix("./")
                try:
                    target = resolve_project_path(self.storage.project_dir(self.ctx), project_path)
                except InvalidPathError:
                    target = None
                if target is not None and not target.exists() and project_path in state["spec"]:
                    assessment = Assessment(
                        decision=Decision.EXPECTED_FAILURE,
                        reason=f"The specified implementation module {project_path} is absent before Coder writes it.",
                    )
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
        if route == "tests" or (route == "code" and phase == "Green"):
            used = self.run_record().repair_count
            if used >= self.settings.max_repairs:
                route = "pause"
                assessment = Assessment(
                    decision=Decision.BLOCKED, reason="Repair budget exhausted. " + assessment.reason
                )
            else:
                self.storage.update_run(self.ctx, repair_count=used + 1)
        self.storage.append_event(
            self.ctx,
            "diagnosis",
            f"Execution {state['execution']['id']}: {assessment.decision.value} — {assessment.reason}",
            role=AgentRole.TESTER,
        )
        return {"assessment": assessment.model_dump(mode="json"), "route": route}

    @staticmethod
    def passed(state):
        check = state["execution"]
        return check["outcome"] == "passed" and check["passed"] > 0

    async def red_review(self, state):
        return await self.assess(state, "Red")

    async def diagnose(self, state):
        return await self.assess(state, "Green")

    async def code(self, state):
        await implement(self.run_agent, self.task(state))

    async def advance(self, state):
        self.storage.append_event(self.ctx, "feature_completed", state["features"][state["index"]]["title"])
        return {"index": state["index"] + 1, "assessment": {}, "execution": {}}

    async def acceptance(self, state):
        review = await review_project(self.run_agent, {
            "request": self.run_record().input.to_json(),
            "spec": state["spec"], "features": state["features"],
            "files": [file.path for file in self.storage.list_project_files(self.ctx)],
            "environment": state.get("environment_result"),
            "checks": [check.to_json() for check in self.storage.list_check_executions(self.ctx)],
        })
        self.storage.append_event(self.ctx, "acceptance", f"{review.decision.value}: {review.reason}", role=AgentRole.ARCHITECT)
        if review.decision == ReviewDecision.APPROVE:
            return {"review": review.model_dump(mode="json"), "route": "advance"}
        used = self.run_record().repair_count
        if review.decision == ReviewDecision.BLOCKED or used >= self.settings.max_repairs:
            reason = review.reason if review.decision == ReviewDecision.BLOCKED else "Repair budget exhausted. " + review.reason
            return {"route": "pause", "assessment": {"reason": reason}}
        self.storage.update_run(self.ctx, repair_count=used + 1)
        target = {
            ReviewDecision.REVISE_PLAN: "plan",
            ReviewDecision.REVISE_CODE: "code",
            ReviewDecision.REVISE_TESTS: "tests",
        }[review.decision]
        return {"route": target, "index": 0 if target == "plan" else len(state["features"]) - 1,
                "review_feedback": review.reason}

    async def report(self, status, summary):
        model = GatewayModel(
            gateway=self.gateway, provider=self.provider, storage=self.storage, context=self.ctx, role="coordinator"
        )
        evidence = {"summary": summary, "request": self.run_record().input.description}
        report = await report_result(model, status, evidence, self.settings.agent_timeout_seconds)
        self.storage.append_event(self.ctx, status, report, role="coordinator")
        return report

    async def pause(self, state):
        reason = state["assessment"]["reason"]
        self.storage.append_event(self.ctx, "blocked", reason, role="coordinator")
        self.storage.update_run(
            self.ctx,
            status="blocked",
            active_role=None,
            error=reason,
            continuation=dict(state),
            coordinator_report=reason,
        )

    def build_graph(self):
        """Declare the TDD steps and their evidence-based transitions."""
        graph = StateGraph(State)
        for name in ("plan", "environment_gate", "architecture", "environment", "environment_fix", "tests", "red", "red_review", "code", "green", "diagnose", "advance", "acceptance", "pause"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "plan")
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
        graph.add_conditional_edges("acceptance", lambda s: END if s["route"] == "advance" else s["route"])
        graph.add_edge("pause", END)
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
            self.storage.package_run(self.ctx)
            report = await self.report(
                "completed",
                f"Completed all {len(result['features'])} planned features. All required tests passed.",
            )
            self.storage.update_run(
                self.ctx, status="completed", active_role=None, continuation=None, coordinator_report=report
            )
        except (WorkflowBlock, AgentBudgetExceeded, OutputParserException) as error:
            reason = (
                str(error)
                if isinstance(error, (WorkflowBlock, AgentBudgetExceeded))
                else "The agent returned an unreadable plan or diagnosis."
            )
            await self.pause({**result, "assessment": {"reason": reason}})
        except LLMError as error:
            await self.pause({**result, "assessment": {"reason": str(error)}})
        except asyncio.CancelledError:
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
