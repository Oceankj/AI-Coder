"""Proposed HTTP handler boundaries; see docs/interfaces.md.

No framework routes are registered. Serialization and access checks are TODO.
"""
from ai_coder.models import GenerationRequest, RunContext


class GenerationAPI:
    async def create_run(self, request: GenerationRequest) -> RunContext:
        # TODO: Validate path/body workspace agreement, persist, and schedule.
        raise NotImplementedError

    async def list_runs(self, workspace_id: str):
        raise NotImplementedError

    async def get_run(self, context: RunContext):
        # TODO: Return status, role, errors, build/test summary, and usage.
        raise NotImplementedError

    async def get_events(self, context: RunContext, after_event_id: str | None = None):
        # TODO: Return ordered scoped events after the optional cursor.
        raise NotImplementedError

    async def list_files(self, context: RunContext):
        raise NotImplementedError

    async def read_file(self, context: RunContext, relative_path: str):
        # TODO: Use the same WorkspaceService path checks as MCP file tools.
        raise NotImplementedError

    async def download(self, context: RunContext):
        # TODO: Serve the generated archive when available.
        raise NotImplementedError


class WorkspaceAPI:
    async def create_workspace(self, name: str):
        # TODO: Allocate a server-generated ID and independent workspace root.
        raise NotImplementedError

    async def list_workspaces(self):
        # TODO: Return workspaces available to the caller.
        raise NotImplementedError

    async def get_workspace(self, workspace_id: str):
        raise NotImplementedError
