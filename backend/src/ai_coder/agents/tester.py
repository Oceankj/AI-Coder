# Author: Ching Kao
# Student ID: 85768427
"""Black-box test authorship and read-only diagnosis of runner evidence."""

from enum import StrEnum

from pydantic import BaseModel, Field

from ai_coder.models import AgentRole


class Decision(StrEnum):
    EXPECTED_FAILURE = "expected_failure"
    ALREADY_PASSING = "already_passing"
    IMPLEMENTATION_DEFECT = "implementation_defect"
    TEST_INVALID = "test_invalid"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class Assessment(BaseModel):
    decision: Decision
    reason: str = Field(min_length=1)


class BrowserAssessment(Assessment):
    next_repair: str = ""


async def diagnose_browser_failure(agent, task):
    return await agent(
        AgentRole.TESTER,
        "Tester diagnosis (browser acceptance). The same host check failed again. "
        "Use the supplied evidence and attempted repairs to distinguish an application defect, "
        "an invalid host test, or an external blocker. Do not edit tests or source. "
        "For an implementation defect, give next_repair only if there is a specific, "
        "untried change supported by evidence. Name the behavior or file and what to change. "
        "Leave next_repair empty when no new repair is justified. The host verifier is operator-owned.",
        task,
        stage="Tester diagnosis (browser acceptance)",
        schema=BrowserAssessment,
        use_file_tools=False,
    )


async def write_cases(agent, task):
    runner = task["testRunner"]
    runner_instruction = (
        "Use Jest test/expect APIs; do not import node:test. For browser DOM tests, use "
        "@jest-environment jsdom in the test file when jest-environment-jsdom is installed. "
        if runner == "jest" else
        "Use node:test and node:assert/strict. The Node runner has no browser DOM by default. "
    )
    repairing = (task.get("assessment") or {}).get("decision") == Decision.TEST_INVALID
    scope = (
        "Repair the invalid tests from assessment.reason and execution.log before writing any new coverage. "
        "Read the existing failing test files named in the execution and correct the identified defects in place, "
        "including files for earlier features. The current feature label does not restrict this repair. "
        "Keep unaffected assertions and valid tests. "
        if repairing else
        "Test the current feature. Use a separate test file for a new feature when possible. "
        "Preserve passing tests for earlier features. When reviewFeedback names missing coverage at final "
        "acceptance, add tests for that named behavior even when it belongs to an earlier feature. "
    )
    coverage = ("Register every repaired test unconditionally. " if repairing else
                "Register a test for every acceptance criterion unconditionally. ")
    if task.get("independentRuntimeVerification"):
        coverage = (
            "The host will check actual user interactions in a browser. Use Node tests for data filtering, metadata,"
            " selection, ordered playback state, persistence, and export logic through documented pure modules or"
            " explicit injected dependencies. Do not import browser bootstrap code in Node without a DOM or search"
            " static HTML for dynamically rendered UI. Replace an invalid browser-only assertion with equivalent"
            " pure behavior coverage when possible, or let the host verify that browser interaction. "
            "Register each unit test unconditionally. "
        )
    if task.get("systemChecks") and not repairing:
        coverage = "Register tests for every remaining criterion not already covered by systemChecks. "
    system_checks = (
        "The systemChecks list describes browser interactions verified by a trusted host fixture. "
        "Leave those interactions to the host. Write pure tests for remaining behavior such as metadata, "
        "label scoring, and audio file filtering. Use native File and Blob and explicit imports from node:url "
        "when applicable. For this import feature, do not import the page bootstrap or mock, delete, or "
        "replace shared browser globals. "
        if task.get("systemChecks") else ""
    )
    await agent(
        AgentRole.TESTER,
        "Tester author. Your only deliverable is executable black-box *.test.js test files. "
        "Never write implementation modules such as add.cjs. The Coder creates those after the Red test. "
        "When repairInstruction is present, apply that specific correction to the named test and preserve other coverage. "
        "Use interfaceLanguage and explicit language clarification for any language-specific assertions. "
        "Use the project-relative paths in projectFiles and the planned paths in the spec. "
        "Resolve module imports and assets from the test file's own directory. A test beside index.html "
        "uses ./index.html and ./src/example.js, via new URL(relativePath, import.meta.url) for assets. "
        "For a nested test, use only as many parent steps as its location requires. Never resolve outside the project. "
        "Use writeFile. Read existingTestFiles in the task and preserve tests that work with the "
        "selected runner; rewrite incompatible tests before adding new ones. "
        + scope + coverage + system_checks + "Do not guard test registration "
        "on an import or variable initialized inside another test; imports may fail in Red, but all "
        "intended tests must still be registered and run in Green. "
        "Make each success test establish all real preconditions through the public interface before triggering its action. "
        "When CSS is required outside systemChecks, test that the entry page links to an existing local stylesheet. "
        "For a directory picker outside systemChecks, dispatch change with actual file fixtures and assert "
        "the imported items or their count. A click alone only opens the picker. "
        "Seed deliberately malformed storage with raw data and keep malformed cases separate from valid cases. "
        "Make each test trigger the behavior it asserts. Never conditionally skip a click or event "
        "because a handler is absent; assert the handler exists or dispatch the event and fail if it does not work. "
        "Do not invent DOM selectors or storage keys absent from the spec; define a consistent public "
        "interface in the tests that Coder can implement, and avoid module cache leaking between tests. "
        "For independent DOM tests import a fresh module instance or explicitly reset its state. "
        "A reload test must preserve storage from the first page, restore it into the new page at the "
        "same origin, and load a fresh module; do not clear the data being tested. "
        "Register cleanup with t.after or afterEach before assertions so failed tests also restore globals. "
        + runner_instruction + "Use Node built-ins or packages "
        "declared in the workspace package.json. You may read package.json and *.test.js files, "
        "but not application source. Use listFiles for source paths; do not retry a denied readFile. "
        "For browser behavior, use an installed DOM package when available or provide "
        "every DOM API the code calls in your test setup. "
        "Restore any globals you replace. "
        "For local-file features use native File/Blob where available, or fixtures that mirror"
        " prototype getters and byte-reading methods. Give metadata cases synthetic embedded"
        " bytes and separate missing-tag cases. Use differing input and result orders when"
        " checking playback, persistence, or export of a transformed selection. "
        "After writing the tests, finish with a brief response and no more tool calls. "
        "Correct a test only for an identified defect or revised spec.",
        task,
        stage="Tester author",
        writable=True,
    )


async def assess_execution(agent, task, phase):
    red = phase == "Red"
    runtime_contract = (
        "The configured host verifier will independently exercise browser interactions at acceptance. "
        "Judge this unit execution for pure data, state, and ordering behavior. Do not require separate "
        "static HTML assertions or real-browser evidence in this step, even when all unit tests pass. "
        "Browser outcomes are still required at final acceptance. "
        if task.get("independentRuntimeVerification") else ""
    )
    prompt = (
        f"Tester diagnosis ({phase}). Compare this exact execution against the feature criteria. "
        + runtime_contract +
        "When revisedTests is present, assess the current files. Treat earlier diagnoses as history "
        "and do not repeat an old finding unless the revised tests still exhibit it. "
        "For a failed execution, use readFile to inspect the failing tests. Check fixture construction"
        " as well as the assertion: verify prerequisites, matching identity fields, and stored fixture"
        " values before blaming application code. Report test_invalid for faulty or inadequate tests, "
        "including contradictory fixture inputs, incomplete DOM mocks, or test setup that fails before assertions. Report blocked only when the runner cannot "
        "support the required behavior or requirements need user input. "
        + (
            "Report expected_failure when the required implementation is not written yet, "
            "including MODULE_NOT_FOUND for the implementation path named in the spec, even if import fails before assertions. "
            "Also treat an absent required export or an implementation stub returning undefined as expected_failure. "
            "Differentiate a Node ReferenceError for an undeclared test helper from an assertion that a project export "
            "was expected to be a function but is undefined. Quote the actual error before assigning blame. "
            "already_passing only when covered and all tests pass."
            if red
            else "Report implementation_defect when required implementation files are missing, "
                 "incomplete, or produce incorrect behavior. Missing implementation is not blocked."
        )
    )
    return await agent(AgentRole.TESTER, prompt, task, stage=f"Tester diagnosis ({phase})", schema=Assessment,
                       use_file_tools=(task.get("execution") or {}).get("outcome") == "failed")
