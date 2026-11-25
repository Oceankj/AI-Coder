# Author: Ching Kao
# Student ID: 85768427
"""Run the production graph with real stdio MCP and Node, replacing only Google."""

import asyncio
import io
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from zipfile import ZipFile
from unittest.mock import AsyncMock

import pytest
from google.genai import types
from google.genai.models import AsyncModels

from fastapi.testclient import TestClient
from scripted_gemini import ScriptedGemini

from ai_coder.main import create_app
from ai_coder.agents.tester import Assessment, Decision, write_cases
from ai_coder.orchestration.tdd import TDDRun, check_evidence
from ai_coder.models import RunContext


@pytest.mark.parametrize("writes_after_correction", [True, False])
def test_writable_step_recovers_once_when_an_agent_only_replies(settings, monkeypatch, writes_after_correction):
    provider = ScriptedGemini()
    author_turns = []

    def generate(*, contents, config, model):
        if not config.system_instruction.startswith("Tester author."):
            return provider(contents=contents, config=config, model=model)
        last = contents[-1].parts[0]
        author_turns.append(last)
        if len(author_turns) == 1:
            part = provider.tool("listFiles", {})
        elif len(author_turns) == 2:
            assert last.function_response.name == "listFiles"
            part = types.Part(text="I described the test but did not save it.")
        elif len(author_turns) == 3:
            assert "No permitted file was written" in last.text
            assert "did not save it" in contents[-2].parts[0].text
            if writes_after_correction:
                return provider(contents=[contents[0]], config=config, model=model)
            part = types.Part(text="Still no saved tests.")
        else:
            assert writes_after_correction and len(author_turns) == 4
            return provider(contents=contents, config=config, model=model)
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))],
        )

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Missing test write"}).json()["id"]
        run = client.portal.call(app.state.runs.start, ws, "Build an adder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        result = app.state.storage.get_run(ws, run.id)
        context = RunContext(ws, run.id)
        events = app.state.storage.list_events(context)
        assert sum(event.type == "write_retry" for event in events) == 1
        assert (app.state.storage.project_dir(context) / "add.test.js").is_file() == writes_after_correction
        if writes_after_correction:
            assert result.status == "completed", result.error
            assert result.checks.tests == "passed"
        else:
            assert len(author_turns) == 3
            assert result.status == "blocked", result.error
            assert result.error == "Tester finished without writing a permitted project file."
            assert result.continuation["resume_node"] == "tests"


def test_coder_tool_budget_after_a_successful_write_continues_to_checks(settings, monkeypatch):
    provider = ScriptedGemini()
    monkeypatch.setattr("ai_coder.agents.runtime.MAX_AGENT_TOOL_CALLS", 1)

    def generate(*, contents, config, model):
        last = contents[-1].parts[0]
        if (config.system_instruction.startswith("Coder.") and last.function_response
                and last.function_response.name == "writeFile"):
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=[provider.tool("listFiles", {})]))])
        return provider(contents=contents, config=config, model=model)

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Verified partial writes"}).json()["id"]
        run = client.portal.call(app.state.runs.start, workspace, "Build an adder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        result = app.state.storage.get_run(workspace, run.id)
        events = app.state.storage.list_events(RunContext(workspace, run.id))
        assert result.status == "completed", result.error
        assert result.checks.tests == "passed"
        assert any(event.type == "agent_interrupted" and "exceeded 1 tool calls" in event.message for event in events)


def test_condensed_check_evidence_keeps_early_and_middle_failure_errors():
    log = "\n".join([
        "TAP version 13", "not ok 1 - filters audio",
        "  error: 'File must be a real Blob'", "  code: 'ERR_INVALID_ARG_TYPE'",
        "  ...", ("test noise\n" * 700), "not ok 2 - renders rows",
        "  error: 'document is not defined'", "  code: 'ERR_TEST_FAILURE'",
        "  ...", ("later output\n" * 700), "# pass 1", "# fail 2",
    ])
    evidence = check_evidence(log)
    assert len(evidence) <= 4000
    assert "File must be a real Blob" in evidence
    assert "document is not defined" in evidence
    assert "# fail 2" in evidence


def test_red_implementation_defect_routes_to_coder_without_replanning():
    state = {"execution": {"id": 7, "outcome": "failed", "failed": 5, "timedOut": False}}
    assessment = Assessment(
        decision=Decision.IMPLEMENTATION_DEFECT,
        reason="The recommendation and playback UI controls are missing.",
    )
    route, corrected = TDDRun.route_assessment(assessment, state, "Red")
    assert route == "code"
    assert corrected.decision == Decision.EXPECTED_FAILURE


def test_green_missing_implementation_returns_to_coder():
    state = {"execution": {"id": 2, "outcome": "failed", "failed": 2, "timedOut": False}}
    assessment = Assessment(
        decision=Decision.EXPECTED_FAILURE,
        reason="src/todo.js is missing after Coder wrote index.html.",
    )
    route, corrected = TDDRun.route_assessment(assessment, state, "Green")
    assert route == "code"
    assert corrected.decision == Decision.IMPLEMENTATION_DEFECT


def test_truncated_implementation_repairs_code_without_reauthoring_tests(settings, monkeypatch):
    provider = ScriptedGemini()
    test_steps = 0
    diagnoses = 0

    def generate(**kwargs):
        nonlocal test_steps, diagnoses
        response = provider(**kwargs)
        prompt = kwargs["config"].system_instruction
        part = response.candidates[0].content.parts[0]
        if prompt.startswith("Tester author.") and part.function_call:
            test_steps += 1
        if prompt.startswith("Tester diagnosis"):
            diagnoses += 1
        if prompt.startswith("Coder.") and part.function_call and provider.implementations == 1:
            part.function_call.args["content"] = "exports.add = function ("
        return response

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Source syntax attribution"}).json()["id"]
        run = client.portal.call(app.state.runs.start, ws, "Build an adder", [])
        client.portal.call(app.state.scheduler.wait_idle)
        result = app.state.storage.get_run(ws, run.id)
        assert result.status == "completed", result.error
        checks = app.state.storage.list_check_executions(RunContext(ws, run.id))
        assert [c.outcome for c in checks] == ["failed", "failed", "passed"]
        assert "Syntax error in implementation file: add.cjs" in checks[1].log
        assert provider.implementations == 2
        assert test_steps == 1
        assert diagnoses == 0


def test_red_node_esm_missing_implementation_routes_to_coder(settings, monkeypatch, tmp_path):
    class Storage:
        run = SimpleNamespace(provider="groq", repair_count=0)

        def get_run(self, *_):
            return self.run

        def project_dir(self, _context):
            return tmp_path

        def list_project_files(self, _context):
            return []

        def update_run(self, _context, **changes):
            for key, value in changes.items():
                setattr(self.run, key, value)

        def append_event(self, *_args, **_kwargs):
            pass

    async def invalid(*_args):
        return Assessment(decision=Decision.TEST_INVALID, reason="The import failed before assertions.")

    monkeypatch.setattr("ai_coder.orchestration.tdd.assess_execution", invalid)
    runner = TDDRun(Storage(), None, settings, RunContext("ws", "run"))
    state = {
        "spec": "Build a todo app with a JavaScript module.", "index": 0,
        "features": [{"title": "Todo", "criteria": ["Add a task"]}],
        "execution": {
            "id": 1, "outcome": "failed", "failed": 1, "timedOut": False,
            "log": f"Cannot find module '{tmp_path / 'todo.js'}' imported from {tmp_path / 'todo.test.js'}",
        },
    }
    result = asyncio.run(runner.assess(state, "Red"))
    assert result["route"] == "code"
    assert result["assessment"]["decision"] == "expected_failure"
    assert runner.run_record().repair_count == 0


def test_tester_prompt_matches_the_runner_selected_by_environment():
    prompts = []

    async def capture(_role, prompt, _task, **_options):
        prompts.append(prompt)

    asyncio.run(write_cases(capture, {"testRunner": "jest", "existingTestFiles": ["old.test.js"]}))
    asyncio.run(write_cases(capture, {"testRunner": "node:test", "existingTestFiles": []}))
    assert "Use Jest test/expect APIs" in prompts[0]
    assert "do not import node:test" in prompts[0]
    assert "Use node:test" in prompts[1]
    assert "Register a test for every acceptance criterion unconditionally" in prompts[1]
    assert "Never conditionally skip a click or event" in prompts[1]


@pytest.mark.parametrize(("missing_path", "expected_route"), [
    ("./add.cjs", "code"), ("./typo.cjs", "tests"),
])
def test_red_missing_specified_module_routes_to_coder(settings, monkeypatch, tmp_path,
                                                       missing_path, expected_route):
    class Storage:
        run = SimpleNamespace(provider="groq", repair_count=0)

        def get_run(self, *_):
            return self.run

        def project_dir(self, _context):
            return tmp_path

        def list_project_files(self, _context):
            return []

        def update_run(self, _context, **changes):
            for key, value in changes.items():
                setattr(self.run, key, value)

        def append_event(self, *_args, **_kwargs):
            pass

    async def invalid(*_args):
        return Assessment(decision=Decision.TEST_INVALID, reason="The module could not be imported.")

    monkeypatch.setattr("ai_coder.orchestration.tdd.assess_execution", invalid)
    runner = TDDRun(Storage(), None, settings, RunContext("ws", "run"))
    state = {
        "spec": "Create add.cjs exporting add.", "index": 0,
        "features": [{"title": "Addition", "criteria": ["add(1,2) is 3"]}],
        "execution": {"id": 1, "outcome": "failed", "failed": 1,
                      "timedOut": False, "log": f"Error: Cannot find module '{missing_path}'"},
    }
    result = asyncio.run(runner.assess(state, "Red"))
    assert result["route"] == expected_route
    assert runner.run_record().repair_count == (0 if expected_route == "code" else 1)


def test_architect_blocker_prevents_completed_run(settings, monkeypatch):
    provider = ScriptedGemini()
    reviews = 0

    def generate(**kwargs):
        nonlocal reviews
        response = provider(**kwargs)
        if kwargs["config"].system_instruction.startswith("Architect acceptance."):
            reviews += 1
            if reviews == 1:
                response.candidates[0].content.parts[0].text = json.dumps({
                    "decision": "blocked", "reason": "The requested browser behavior has not been verified."
                })
        return response

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Review gate"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{run}"
        detail = client.get(base).json()
        assert detail["status"] == "blocked"
        assert detail["checks"]["tests"] == "passed"
        assert "browser behavior" in detail["error"]
        assert client.get(base + "/download").status_code == 409
        assert chat(client, workspace, "Use integers", runId=run)["runId"] == run
        client.portal.call(app.state.scheduler.wait_idle)
        resumed = client.get(base).json()
        assert resumed["status"] == "completed", resumed["error"]


def test_architect_dependencies_are_installed_in_workspace_before_tests(settings, monkeypatch, tmp_path):
    provider = ScriptedGemini()

    def generate(**kwargs):
        response = provider(**kwargs)
        if kwargs["config"].system_instruction.startswith("Architect environment."):
            response.candidates[0].content.parts[0].text = json.dumps({
                "reason": "The project needs a DOM test package.", "packages": {"jsdom": "^26.1.0"}
            })
        return response

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" >> setup-calls.txt\n"
        "if [ \"$1\" = install ]; then printf '{}\\n' > package-lock.json; "
        "else mkdir -p node_modules/jsdom; fi\n"
    )
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Dependencies"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{run}"
        assert client.get(base).json()["status"] == "completed"
        project = settings.workspaces_root / workspace / "project"
        assert (project / "node_modules" / "jsdom").is_dir()
        assert (project / "setup-calls.txt").read_text().splitlines() == ["install", "ci"]
        with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archive:
            assert {"package.json", "package-lock.json"} <= set(archive.namelist())
            assert not any(name.startswith("node_modules/") or name.startswith(".npm-cache/")
                           for name in archive.namelist())


def test_existing_workspace_bypasses_environment_architect(settings, monkeypatch):
    provider = ScriptedGemini()
    environment_calls = 0

    def generate(**kwargs):
        nonlocal environment_calls
        if kwargs["config"].system_instruction.startswith("Architect environment."):
            environment_calls += 1
        return provider(**kwargs)

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Reusable environment"}).json()["id"]
        first = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        assert client.get(f"/api/workspaces/{workspace}/runs/{first}").json()["status"] == "completed"
        assert environment_calls == 1
        assert (settings.workspaces_root / workspace / "project" / ".ai-coder-environment.json").is_file()

        second = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{second}"
        assert client.get(base).json()["status"] == "completed"
        assert environment_calls == 1
        events = client.get(base + "/events").json()["events"]
        assert any(event["type"] == "environment_bypassed" for event in events)
        assert not any(event["type"] == "environment_plan" for event in events)
        with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archive:
            assert ".ai-coder-environment.json" not in archive.namelist()


def test_reused_environment_error_consults_architect(settings, monkeypatch, tmp_path):
    provider = ScriptedGemini()
    environment_calls = 0

    def generate(**kwargs):
        nonlocal environment_calls
        if kwargs["config"].system_instruction.startswith("Architect environment."):
            environment_calls += 1
        return provider(**kwargs)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = install ]; then printf '{}\\n' > package-lock.json; "
        "else mkdir -p node_modules/jsdom; fi\n"
    )
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Broken environment"}).json()["id"]
        first = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        assert client.get(f"/api/workspaces/{workspace}/runs/{first}").json()["status"] == "completed"
        project = settings.workspaces_root / workspace / "project"
        (project / "package.json").write_text(json.dumps({"dependencies": {"jsdom": "file:../bad"}}))

        second = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{second}"
        assert client.get(base).json()["status"] == "completed"
        assert environment_calls == 2
        events = client.get(base + "/events").json()["events"]
        assert any(event["type"] == "environment_bypassed" for event in events)
        assert any(event["type"] == "environment_failed" for event in events)
        assert any(event["type"] == "environment_plan" for event in events)


def test_missing_test_package_after_bypass_consults_architect(settings, monkeypatch, tmp_path):
    provider = ScriptedGemini()
    environment_calls = 0
    second_run = False

    def generate(**kwargs):
        nonlocal environment_calls
        response = provider(**kwargs)
        prompt = kwargs["config"].system_instruction
        part = response.candidates[0].content.parts[0]
        if prompt.startswith("Architect environment."):
            environment_calls += 1
            if environment_calls == 2:
                part.text = json.dumps({"reason": "The test needs jsdom.", "packages": {"jsdom": "^26.1.0"}})
        elif second_run and prompt.startswith("Tester author.") and part.function_call:
            part.function_call.args["content"] = "require('jsdom');\n" + part.function_call.args["content"]
        return response

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = install ]; then printf '{}\\n' > package-lock.json; "
        "else mkdir -p node_modules/jsdom; "
        "printf '{\"name\":\"jsdom\",\"main\":\"index.js\"}\\n' > node_modules/jsdom/package.json; "
        "printf 'module.exports = {};\\n' > node_modules/jsdom/index.js; fi\n"
    )
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "New package"}).json()["id"]
        first = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        assert client.get(f"/api/workspaces/{workspace}/runs/{first}").json()["status"] == "completed"

        second_run = True
        second = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{second}"
        detail = client.get(base).json()
        assert detail["status"] == "completed", detail["error"]
        assert environment_calls == 2
        events = client.get(base + "/events").json()["events"]
        assert any(e["type"] == "environment_failed" and "jsdom" in e["message"] for e in events)
        assert any(e["type"] == "environment_plan" for e in events)


def test_environment_install_failure_routes_to_coder_and_recovers(settings, monkeypatch, tmp_path):
    provider = ScriptedGemini()

    def generate(**kwargs):
        response = provider(**kwargs)
        if kwargs["config"].system_instruction.startswith("Architect environment."):
            response.candidates[0].content.parts[0].text = json.dumps({
                "reason": "DOM tests need a package.", "packages": {"jsdom": "^26.1.0"}
            })
        return response

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "if [ ! -f failed-once ]; then : > failed-once; echo 'npm error code E404'; exit 1; fi\n"
        "if [ \"$1\" = install ]; then printf '{}\\n' > package-lock.json; "
        "else mkdir -p node_modules/jsdom; fi\n"
    )
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Setup repair"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{workspace}/runs/{run}"
        assert client.get(base).json()["status"] == "completed"
        events = client.get(base + "/events").json()["events"]
        assert any(e["type"] == "environment_failed" and "E404" in e["message"] for e in events)
        assert any(e["type"] == "role_started" and e["message"] == "Coder environment repair" for e in events)


def test_red_blocker_gets_one_test_harness_repair_before_pausing(monkeypatch):
    class Storage:
        run = SimpleNamespace(provider="groq", repair_count=0)
        events = []

        def get_run(self, *_):
            return self.run

        def update_run(self, _context, **changes):
            for key, value in changes.items():
                setattr(self.run, key, value)

        def append_event(self, _context, kind, message, **_kwargs):
            self.events.append((kind, message))

        def list_project_files(self, _context):
            return []

    async def blocked(*_args):
        return Assessment(decision=Decision.BLOCKED, reason="document.addEventListener is not a function")

    monkeypatch.setattr("ai_coder.orchestration.tdd.assess_execution", blocked)
    storage = Storage()
    runner = TDDRun(storage, None, SimpleNamespace(max_repairs=3, project_verifier=None), RunContext("ws", "run"))
    state = {
        "spec": "Persist tasks", "index": 0,
        "features": [{"title": "Load tasks", "criteria": ["Show saved tasks"]}],
        "execution": {"id": 1, "outcome": "failed", "failed": 2,
                      "timedOut": False, "log": "failureType: 'hookFailed'"},
    }
    first = asyncio.run(runner.assess(state, "Red"))
    assert first["route"] == "tests"
    assert storage.run.repair_count == 1
    second = asyncio.run(runner.assess(state, "Red"))
    assert second["route"] == "pause"
    storage.run.repair_count = 0
    state["execution"]["log"] = "failureType: 'testCodeFailure'"
    genuine_block = asyncio.run(runner.assess(state, "Red"))
    assert genuine_block["route"] == "pause"


def chat(client, workspace, text, **context):
    response = client.post(
        "/api/chat",
        json={"workspaceId": workspace, **context, "messages": [{"role": "user", "content": text}]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_chat_to_verified_download(settings, monkeypatch):
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=ScriptedGemini(block=True)))
    app = create_app(replace(settings, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "TDD integration"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        base = f"/api/workspaces/{workspace}/runs/{run}"
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == "blocked", detail
        assert "numeric types" in detail["error"]
    # Restart between clarification turns to prove the checkpoint is durable.
    app = create_app(replace(settings, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        assert chat(client, workspace, "Use integers", runId=run)["runId"] == run
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == "completed", detail
        assert detail["checks"]["tests"] == "passed"
        assert "completed" in chat(client, workspace, "progress", runId=run)["message"]["content"]
        assert len(client.get(f"/api/workspaces/{workspace}/runs").json()) == 1
        directory = settings.workspaces_root / workspace / "runs" / run
        assert (directory / "artifacts" / f"{run}.zip").is_file()
        checks = json.loads((directory / "checks.json").read_text())["executions"]
        assert [c["outcome"] for c in checks] == ["failed", "failed", "failed", "passed"]
        assert [c["passed"] for c in checks] == [0, 0, 0, 1]
        assert "MODULE_NOT_FOUND" in checks[0]["log"]
        assert "0 !== 3" in checks[-2]["log"]
        calls = [json.loads(line) for line in settings.llm_record_path.read_text().splitlines()]
        run_calls = [c for c in calls if c.get("runId") == run and c["event"] == "completed"]
        assert {c["role"] for c in run_calls} == {"planner", "architect", "tester", "coder", "coordinator"}
        assert detail["usage"]["apiCalls"] == len(run_calls)
        assert detail["coordinatorReport"] and "All required tests passed" in detail["coordinatorReport"]
        events = client.get(base + "/events").json()["events"]
        assert {e["role"] for e in events if e["type"] == "role_started"} == {"planner", "architect", "tester", "coder"}
        assert any(e["type"] == "environment_ready" for e in events)
        assert any(e["type"] == "acceptance" and e["message"].startswith("approve:") for e in events)
        assert all(e["role"] in {"tester", "coder"} for e in events if e["type"] == "tool_call")
        assert all("role" not in e for e in events if e["type"] == "checks")
        assert any(e["type"] == "diagnosis" and "expected_failure" in e["message"] for e in events)
        with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archive:
            assert {"add.cjs", "add.test.js"} <= set(archive.namelist())


@pytest.mark.parametrize(
    "max_repairs, second_feature, expected_status", [(0, False, "blocked"), (3, True, "completed")]
)
def test_repair_limit_and_feature_routing(
    settings, monkeypatch, max_repairs, second_feature, expected_status
):
    provider = ScriptedGemini(second_feature=second_feature)
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=provider))
    app = create_app(replace(settings, max_repairs=max_repairs, gemini_api_key="integration-fixture"))
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "TDD routing"}).json()["id"]
        run = chat(client, workspace, "Build an adder")["runId"]
        base = f"/api/workspaces/{workspace}/runs/{run}"
        client.portal.call(app.state.scheduler.wait_idle)
        detail = client.get(base).json()
        assert detail["status"] == expected_status, detail
        events = client.get(base + "/events").json()["events"]
        if expected_status == "blocked":
            assert "Repair budget exhausted" in detail["error"]
            assert provider.implementations == 1
            assert client.get(base + "/download").status_code == 409
        else:
            directory = settings.workspaces_root / workspace / "runs" / run
            tasks = json.loads((directory / "tasks.json").read_text())["tasks"]
            assert sum(t["role"] == "planner" for t in tasks) == 1
            assert all(t["status"] == "submitted" for t in tasks)
            coder_tasks = [t for t in tasks if t["role"] == "coder"]
            assert [t["feature"]["number"] for t in coder_tasks] == [1, 1]
            assert all(t["plan"] == provider.spec["spec"] for t in coder_tasks)
            assert "0 !== 3" in coder_tasks[-1]["previousFailure"]
            diagnoses = [e["message"] for e in events if e["type"] == "diagnosis"]
            assert any("test_invalid" in d for d in diagnoses)
            assert any("already_passing" in d for d in diagnoses)
            assert [e["message"] for e in events if e["type"] == "feature_completed"] == [
                "Addition",
                "Adding zero",
            ]
            assert "2 passed, 0 failed" in [e["message"] for e in events if e["type"] == "checks"][-1]
            assert provider.implementations == 2


@pytest.mark.parametrize("titles,status", [([], "blocked"), (["   "], "blocked"), (["A", "B"], "failed")])
def test_invalid_plan_stops_before_implementation(settings, monkeypatch, titles, status):
    provider = ScriptedGemini()
    provider.spec["features"] = [{"title": title, "criteria": ["Returns 3"]} for title in titles]
    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=provider))
    app = create_app(replace(settings, gemini_api_key="fixture", max_features=1))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Planning"}).json()["id"]
        base = f"/api/workspaces/{ws}/runs"
        run = client.portal.call(app.state.runs.start, ws, "Build an adder", []).id
        client.portal.call(app.state.scheduler.wait_idle)
        result = client.get(f"{base}/{run}").json()
        assert result["status"] == status and result["error"]
        assert result["activeRole"] is None and result["checks"]["tests"] == "not_run"
        assert provider.implementations == 0


def test_planner_timeout_releases_workspace_and_shutdown_cancels_next_run(settings, monkeypatch):
    async def exercise():
        started = asyncio.Queue()
        cancelled = []
        async def stalled(**kwargs):
            call = len(cancelled) + 1
            started.put_nowait(call)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(call)

        monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=stalled))
        app = create_app(replace(settings, agent_timeout_seconds=0.5, gemini_api_key="fixture"))
        storage, runs, scheduler = app.state.storage, app.state.runs, app.state.scheduler
        ws = storage.create_workspace("Scheduling").id
        first = runs.start(ws, "First", [])
        assert await asyncio.wait_for(started.get(), 10) == 1
        second = runs.start(ws, "Second", [])
        assert storage.get_run(ws, first.id).active_role.value == "planner"
        assert storage.get_run(ws, second.id).status == "queued"
        assert await asyncio.wait_for(started.get(), 10) == 2
        assert storage.get_run(ws, first.id).status == "failed"
        assert storage.get_run(ws, second.id).status == "running"
        await scheduler.shutdown()
        interrupted = storage.get_run(ws, second.id)
        assert interrupted.status == "failed" and interrupted.active_role is None
        assert cancelled == [1, 2]

    asyncio.run(exercise())


@pytest.mark.parametrize("case", ["no_test_file", "false_pass", "shared_budget"])
def test_unverified_feature_cannot_complete(settings, monkeypatch, case):
    provider = ScriptedGemini(second_feature=case == "shared_budget")

    def generate(**kwargs):
        reply = provider(**kwargs)
        part = reply.candidates[0].content.parts[0]
        phase = kwargs["config"].system_instruction
        if case == "no_test_file" and phase.startswith("Tester author."):
            part.function_call = None
            part.text = "All tests are ready."
        elif case == "false_pass" and phase.startswith("Tester diagnosis (Red)"):
            part.text = json.dumps({"decision": "already_passing", "reason": "Looks correct."})
        elif case == "shared_budget" and phase.startswith("Coder.") and part.function_call:
            # The first feature passes after repair. The zero case still fails.
            part.function_call.args["content"] = part.function_call.args["content"].replace(
                "a + b", "(b === 0 ? -1 : a + b)"
            )
        return reply

    monkeypatch.setattr(AsyncModels, "generate_content", AsyncMock(side_effect=generate))
    app = create_app(replace(settings, gemini_api_key="fixture", max_repairs=2))
    with TestClient(app) as client:
        ws = client.post("/api/workspaces", json={"name": "Evidence"}).json()["id"]
        if case == "false_pass":
            # Exercise conflicting diagnosis on a failing assertion, not an
            # absent module now handled deterministically before diagnosis.
            project = settings.workspaces_root / ws / "project"
            project.mkdir(exist_ok=True)
            (project / "add.cjs").write_text("exports.add = () => 0;")
        run = chat(client, ws, "Build an adder")["runId"]
        client.portal.call(app.state.scheduler.wait_idle)
        base = f"/api/workspaces/{ws}/runs/{run}"
        detail = client.get(base).json()
        assert detail["status"] == "blocked"
        assert detail["checks"]["tests"] == ("not_run" if case == "no_test_file" else "failed")
        assert client.get(base + "/download").status_code == 409
        if case == "shared_budget":
            assert "Repair budget exhausted" in detail["error"]
            events = client.get(base + "/events").json()["events"]
            assert [e["message"] for e in events if e["type"] == "feature_completed"] == ["Addition"]
        else:
            assert provider.implementations == 0
