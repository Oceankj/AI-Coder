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


async def specify(agent, payload, limit):
    plan = await agent(
        AgentRole.PLANNER,
        "Planner. Specify observable JS behavior, module paths and public interfaces. "
        f"Plan at most {limit} ordered features with testable acceptance criteria."
        " Include every requested behavior, including empty-input and persistence requirements."
        " For browser apps specify concrete DOM selectors, the storage key, and a consistent module format"
        " in the spec so Tester and Coder share one public contract."
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
