from ai_coder.models import RunContext


class ExecutionTools:
    async def run_checks(self, context: RunContext):
        # TODO: Run configured build/tests inside the run sandbox with timeout.
        # TODO: Return exit code, bounded stdout/stderr, and test results.
        raise NotImplementedError
