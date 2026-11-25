# Author: Ching Kao
# Student ID: 85768427
"""Technical environment plan and evidence-based project acceptance."""

from enum import StrEnum

from pydantic import BaseModel, Field

from ai_coder.models import AgentRole


class EnvironmentPlan(BaseModel):
    reason: str = Field(min_length=1)
    packages: dict[str, str] = Field(default_factory=dict)


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE_PLAN = "revise_plan"
    REVISE_CODE = "revise_code"
    REVISE_TESTS = "revise_tests"
    BLOCKED = "blocked"


class ProjectReview(BaseModel):
    decision: ReviewDecision
    reason: str = Field(min_length=1)


async def design_environment(agent, payload):
    return await agent(
        AgentRole.ARCHITECT,
        "Architect environment. Decide from the request, spec, existing file names and "
        "package manifest supplied in the task. Choose only the "
        "registry npm packages required by this request and its Node tests; use explicit "
        "semver versions. Return an empty packages object when Node built-ins suffice. "
        "Do not request shell commands, install scripts, URLs, or a different runtime. "
        "The environment executor installs packages inside this workspace with scripts disabled.",
        payload,
        stage="Architect environment",
        schema=EnvironmentPlan,
        use_file_tools=False,
    )


async def review_project(agent, payload):
    return await agent(
        AgentRole.ARCHITECT,
        "Architect acceptance. Compare the original request and every requirement with the "
        "planned features, project file contents, environment result, and recorded passing checks. "
        "Use readFile to inspect omittedReviewFiles when any are relevant to the verdict. "
        "The original user request is authoritative. A detail introduced only by the plan is not a new user"
        " requirement. Use the host-provided projectVerification verdict as evidence for the behaviors it actually observed. "
        "Approve only when the whole project is "
        "usable and covered by the evidence. If something is missing, return revise_plan, "
        "revise_code, or revise_tests with a specific repair reason. Return blocked only "
        "for a genuine external limitation or a question requiring the user. "
        "If tests skip required behavior or register conditionally, choose revise_tests before "
        "judging implementation; a passing check with missing coverage is insufficient. "
        "Trace requested browser actions from actual HTML handlers to the data used by their"
        " visible outcomes. Check that native File/Blob references survive import and that"
        " embedded metadata support reads bytes when required. Check that saved or exported"
        " data matches the user-selected order and that a fresh page offers the claimed"
        " reopening flow. Reject missing wiring even when isolated helpers pass. "
        "When host projectVerification is present, use it for the browser behaviors it actually observed."
        " Check that the documented data and state behaviors are covered by Node tests. The browser outcomes"
        " do not need duplicated static HTML assertions in the unit suite. "
        "Do not claim an unobserved build or browser check passed.",
        payload,
        stage="Architect acceptance",
        schema=ProjectReview,
        use_file_tools=bool(payload.get("omittedReviewFiles")),
    )
