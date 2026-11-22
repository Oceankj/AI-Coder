# Author: Ching Kao
# Student ID: 85768427
"""Implement one feature against the spec, black-box tests and recorded failure."""

from ai_coder.models import AgentRole


async def implement(agent, task):
    await agent(
        AgentRole.CODER,
        "Coder. Implement or repair only this feature using writeFile. "
        "Read its tests and failure output. Create every implementation file required by the tests "
        "before finishing. After writing all required files, finish with a brief response and "
        "no more tool calls. Preserve other features. Do not change tests.",
        task,
        stage="Coder",
        writable=True,
    )
