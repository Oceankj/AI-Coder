"""Shared internal models; API serialization is still TODO."""
from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"


@dataclass(frozen=True)
class RunContext:
    workspace_id: str
    run_id: str


@dataclass(frozen=True)
class GenerationRequest:
    workspace_id: str
    description: str
    requirements: tuple[str, ...]


@dataclass(frozen=True)
class AgentTask:
    context: RunContext
    role: AgentRole
    instructions: str


@dataclass(frozen=True)
class AgentResult:
    context: RunContext
    role: AgentRole
    summary: str
    artifact_paths: tuple[str, ...] = ()
