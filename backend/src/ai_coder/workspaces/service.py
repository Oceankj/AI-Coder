"""Owns workspace creation, scoped path resolution, locks, and cleanup."""
from pathlib import Path
from ai_coder.models import RunContext


class WorkspaceService:
    def __init__(self, root: Path):
        self.root = root

    def create_workspace(self, name: str):
        # TODO: Generate an opaque ID, persist metadata, and create its root.
        raise NotImplementedError

    def run_root(self, context: RunContext) -> Path:
        # TODO: Validate IDs and membership; resolve root/<workspace>/runs/<run>.
        raise NotImplementedError

    def resolve_file(self, context: RunContext, relative_path: str) -> Path:
        # TODO: Resolve within this run's project/ root and reject escapes.
        raise NotImplementedError
