from ai_coder.models import RunContext


class FileTools:
    async def list_files(self, context: RunContext, relative_directory: str = "."):
        # TODO: List paths within the run project; reject escaping symlinks.
        raise NotImplementedError

    async def read_file(self, context: RunContext, relative_path: str) -> str:
        # TODO: Resolve through WorkspaceService and read only within this run.
        raise NotImplementedError

    async def write_file(self, context: RunContext, relative_path: str, content: str) -> None:
        # TODO: Reject absolute paths, traversal, and symlinks escaping the root.
        raise NotImplementedError
