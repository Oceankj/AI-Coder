# Author: Ching Kao
# Student ID: 85768427
"""Planner output and acceptance criteria for a development request."""

from pydantic import BaseModel, ConfigDict, Field

from ai_coder.models import AgentRole


class Feature(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    criteria: list[str] = Field(min_length=1)


class Plan(BaseModel):
    spec: str = Field(min_length=1)
    features: list[Feature] = Field(min_length=1)
    interface_language: str | None = Field(default=None, max_length=80)


async def specify(agent, payload, limit):
    plan = await agent(
        AgentRole.PLANNER,
        "Planner. Specify observable JS behavior, module paths and public interfaces. "
        f"Plan at most {limit} ordered features with testable acceptance criteria."
        " Include every requested behavior, including empty-input and persistence requirements."
        " For an application interface, set interface_language to the explicit requested language or, by default, "
        "the language of the substantive original user brief. Read Original user messages when available. "
        "Use their wording to resolve a conflict with the Coordinator summary. A short confirmation does not "
        "change the language. Keep the spec and feature descriptions in the language of the original brief."
        " For browser apps specify concrete DOM selectors, the storage key, and a consistent module format"
        " in the spec so Tester and Coder share one public contract."
        " When independentRuntimeVerification is true, separate observable browser outcomes from unit test"
        " seams. Define pure module exports for data, ordering, and state. Let actual-browser checks"
        " validate interactions. A selector contract describes the rendered UI and may be created dynamically."
        " Describe the actual user action, input, and visible outcome for browser features."
        " If the request calls for CSS styling, include a linked local stylesheet in the existing interface feature."
        " For local-file input, specify supported inputs, relative paths, real embedded metadata"
        " and its fallback, and a public seam that can be tested with synthetic file bytes."
        " When an action creates an ordered selection, specify which subsequent actions use it"
        " and what users see on a fresh page after restoring saved data."
        " Group related behavior into cohesive product features; writing tests is part of each feature,"
        " not a separate feature."
        " Preserve and extend existing files when present; do not plan a replacement project."
        " On clarification revise only the current feature.",
        payload,
        stage="Planner",
        schema=Plan,
    )
    if len(plan.features) > limit:
        raise ValueError("Planner exceeded the feature limit.")
    return plan
