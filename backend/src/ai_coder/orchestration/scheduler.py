# Author: Ching Kao
# Student ID: 85768427
"""Starts runs in the background and keeps one run at a time per workspace.

The chat entry point must answer immediately with status "queued", while a run can take
minutes. The route therefore hands the run to `RunScheduler.submit`, which
starts an asyncio task in the server's event loop and returns at once.

Runs of the same workspace wait for each other (a per-workspace lock), so two
runs never write to the same workspace at the same time. Runs of different
workspaces may run concurrently.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from ai_coder.models import RunContext
from ai_coder.orchestration.tdd import TDDWorkflow


class RunScheduler:
    def __init__(self, workflow: TDDWorkflow) -> None:
        self._workflow = workflow
        self._workspace_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Strong references: the event loop keeps only weak references to tasks.
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, context: RunContext) -> asyncio.Task[None]:
        """Start the run in the background. Must be called inside the event loop."""
        task = asyncio.create_task(self._execute(context), name=f"run-{context.run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_idle(self) -> None:
        """Wait until every submitted run has finished (used by tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel unfinished runs.

        A running run is marked failed by the orchestrator. A run still waiting
        for its workspace lock stays "queued" on disk; the next startup marks
        it failed (`FileStorage.fail_interrupted_runs`).
        """
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _execute(self, context: RunContext) -> None:
        async with self._workspace_locks[context.workspace_id]:
            await self._workflow.run(context)
