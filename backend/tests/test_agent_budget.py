# Author: Ching Kao
# Student ID: 85768427
"""Bound every agent loop, including successful repeated calls and tool errors."""

import pytest

from ai_coder.agents.runtime import (
    AgentBudget, AgentBudgetExceeded, MAX_AGENT_MODEL_CALLS, MAX_AGENT_TOOL_CALLS,
    MAX_CONSECUTIVE_TOOL_ERRORS,
)


def test_successful_tool_loop_and_model_loop_both_stop():
    budget = AgentBudget()
    for _ in range(MAX_AGENT_TOOL_CALLS):
        budget.use_tool()
        budget.tool_result("listFiles", failed=False)
    with pytest.raises(AgentBudgetExceeded, match="tool calls"):
        budget.use_tool()

    budget = AgentBudget()
    for _ in range(MAX_AGENT_MODEL_CALLS):
        budget.use_model()
    with pytest.raises(AgentBudgetExceeded, match="model calls"):
        budget.use_model()


def test_consecutive_failures_stop_but_success_resets_the_allowance():
    budget = AgentBudget()
    for _ in range(MAX_CONSECUTIVE_TOOL_ERRORS - 1):
        budget.tool_result("readFile", failed=True)
    budget.tool_result("listFiles", failed=False)
    for _ in range(MAX_CONSECUTIVE_TOOL_ERRORS - 1):
        budget.tool_result("writeFile", failed=True)
    with pytest.raises(AgentBudgetExceeded, match="Tool calls failed"):
        budget.tool_result("writeFile", failed=True)
