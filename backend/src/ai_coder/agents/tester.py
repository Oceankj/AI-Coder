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


async def write_cases(agent, task):
    runner = task["testRunner"]
    runner_instruction = (
        "Use Jest test/expect APIs; do not import node:test. For browser DOM tests, use "
        "@jest-environment jsdom in the test file when jest-environment-jsdom is installed. "
        if runner == "jest" else
        "Use node:test and node:assert/strict. The Node runner has no browser DOM by default. "
    )
    await agent(
        AgentRole.TESTER,
        "Tester author. Your only deliverable is executable black-box *.test.js test files. "
        "Never write implementation modules such as add.cjs. The Coder creates those after the Red test. "
        "Use writeFile. Read existingTestFiles in the task and preserve tests that work with the "
        "selected runner; rewrite incompatible tests before adding new ones. "
        + runner_instruction + "Use Node built-ins or packages "
        "declared in the workspace package.json. You may read package.json and *.test.js files, "
        "but not application source. Use listFiles for source paths; do not retry a denied readFile. "
        "For browser behavior, use an installed DOM package when available or provide "
        "every DOM API the code calls in your test setup. "
        "Restore any globals you replace. "
        "After writing the tests, finish with a brief response and no more tool calls. "
        "Correct a test only for an identified defect or revised spec.",
        task,
        stage="Tester author",
        writable=True,
    )


async def assess_execution(agent, task, phase):
    red = phase == "Red"
    prompt = (
        f"Tester diagnosis ({phase}). Compare this exact execution against the feature criteria. "
        "Report test_invalid for faulty or inadequate tests, including incomplete DOM mocks or "
        "test setup that fails before assertions. Report blocked only when the runner cannot "
        "support the required behavior or requirements need user input. "
        + (
            "Report expected_failure when the required implementation is not written yet, "
            "including MODULE_NOT_FOUND for the implementation path named in the spec, even if import fails before assertions; "
            "already_passing only when covered and all tests pass."
            if red
            else "Report implementation_defect when required implementation files are missing, "
                 "incomplete, or produce incorrect behavior. Missing implementation is not blocked."
        )
    )
    return await agent(AgentRole.TESTER, prompt, task, stage=f"Tester diagnosis ({phase})", schema=Assessment)
