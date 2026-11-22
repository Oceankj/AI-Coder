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
        "Tester author. Write executable black-box *.test.js cases "
        "from the spec using writeFile and node:test. Preserve earlier tests. Use built-in Node modules. "
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
            else "Report implementation_defect for an application failure."
        )
    )
    return await agent(AgentRole.TESTER, prompt, task, stage=f"Tester diagnosis ({phase})", schema=Assessment)
