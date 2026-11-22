# Author: Shih-Yun Huang
# Student ID: 20645816
"""What one MCP server session is allowed to act on.

The MCP server starts with a workspace, a run, and a role fixed on its command
line (step 4). Those values go into a `ToolScope` once, and every tool reads
them from there. Tool arguments from the LLM never choose the workspace, run,
or role, so a model cannot reach another run or pretend to be another agent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_coder.models import AgentRole, RunContext
from ai_coder.storage.repository import FileStorage


@dataclass(frozen=True)
class ToolScope:
    """The run and role one MCP server session works for."""

    storage: FileStorage  # same workspaces root as the backend
    context: RunContext  # which workspace and run
    role: AgentRole  # which agent is calling the tools

    @property
    def project_dir(self) -> Path:
        """The run's project/ folder; every file path is relative to it."""
        return self.storage.project_dir(self.context)
