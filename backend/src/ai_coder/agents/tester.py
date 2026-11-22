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
    await agent(
        AgentRole.TESTER,
        "Tester author. Your only deliverable is executable black-box *.test.js test files. "
        "Never write implementation modules such as add.cjs. The Coder creates those after the Red test. "
        "Use writeFile and node:test. Preserve earlier tests. Use built-in Node modules. "
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
        "Report test_invalid for faulty or inadequate tests and blocked for ambiguous requirements "
        "or environmental problems. "
        + (
            "Report expected_failure only when the new feature is missing; "
            "already_passing only when covered and all tests pass."
            if red
            else "Report implementation_defect when required implementation files are missing, "
                 "incomplete, or produce incorrect behavior. Missing implementation is not blocked."
        )
    )
    return await agent(AgentRole.TESTER, prompt, task, stage=f"Tester diagnosis ({phase})", schema=Assessment)
