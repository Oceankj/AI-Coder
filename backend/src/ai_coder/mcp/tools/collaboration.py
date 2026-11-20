# Author: Shih-Yun Huang
# Student ID: 20645816
"""Collaboration tools: getTask and submitResult.

Agents never talk to each other directly. The orchestrator writes a task for a
role into tasks.json (the shared blackboard); the agent reads it with getTask
and answers with submitResult. The next agent's task then carries what it needs
(for example the Planner's plan), so the handoff happens through these tools.
"""
from __future__ import annotations

from typing import Any, Literal

from ai_coder.models import AgentRole
from ai_coder.mcp.tools.scope import ToolScope


class CollaborationTools:
    """getTask and submitResult for the role bound in `scope`."""

    def __init__(self, scope: ToolScope) -> None:
        """Bind the tools to one run and role."""
        self.scope = scope

    def get_task(self) -> dict[str, Any]:
        """Return this role's latest task as camelCase JSON (see tasks.json).

        Raises LookupError if the orchestrator has not published a task for
        this role yet.
        """
        task = self.scope.storage.get_current_task(self.scope.context, self.scope.role)
        if task is None:
            raise LookupError(f"No task has been published for the {self.scope.role.value} yet.")
        return task.to_json()

    def submit_result(
        self,
        summary: str,
        outcome: Literal["success", "failure"],
        artifact_paths: list[str] | None = None,
        features: list[dict[str, str]] | None = None,
    ) -> str:
        """Record this role's result on its latest task and return a confirmation.

        `features` is the Planner's ordered list of {title, description}; it is
        required for the Planner and refused for other roles. Checking it here,
        instead of only in the orchestrator, gives the model a chance to fix
        its call rather than failing the whole run.
        """
        role = self.scope.role
        features = features or []
        if role is AgentRole.PLANNER:
            self._check_planner_features(features)
        elif features:
            raise ValueError(f"Only the Planner submits features; the {role.value} must leave them out.")

        self.scope.storage.submit_result(
            self.scope.context,
            role,
            summary=summary,
            artifact_paths=artifact_paths or [],
            outcome=outcome,
            features=features,
        )
        return f"Result recorded for the {role.value}."

    def _check_planner_features(self, features: list[dict[str, str]]) -> None:
        """Raise ValueError if the Planner's feature list is empty or too long."""
        limit = self.scope.max_features
        if not features:
            raise ValueError("The Planner must submit at least one feature in `features`.")
        if limit is not None and len(features) > limit:
            raise ValueError(
                f"The Planner may submit at most {limit} features; it sent {len(features)}. "
                "Merge related features and submit again."
            )
