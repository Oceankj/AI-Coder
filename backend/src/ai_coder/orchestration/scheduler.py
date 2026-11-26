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

from ai_coder.models import RUN_STOP_REQUESTED, RunContext
from ai_coder.orchestration.tdd import TDDWorkflow


class RunScheduler:
    def __init__(self, workflow: TDDWorkflow) -> None:
        self._workflow = workflow
        self._workspace_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Strong references: the event loop keeps only weak references to tasks.
        self._tasks: dict[RunContext, asyncio.Task[None]] = {}

    def submit(self, context: RunContext) -> asyncio.Task[None]:
        """Start the run in the background. Must be called inside the event loop."""
        task = asyncio.create_task(self._execute(context), name=f"run-{context.run_id}")
        self._tasks[context] = task

        def forget(done: asyncio.Task[None]) -> None:
            if self._tasks.get(context) is done:
                self._tasks.pop(context)

        task.add_done_callback(forget)
        return task

    async def stop(self, context: RunContext) -> None:
        task = self._tasks.get(context)
        if task is not None and not task.done():
            if not task.cancelling():
                task.cancel(RUN_STOP_REQUESTED)
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))

    async def wait_idle(self) -> None:
        """Wait until every submitted run has finished (used by tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel unfinished runs.

        A running run is marked failed by the orchestrator. A run still waiting
        for its workspace lock stays "queued" on disk; the next startup marks
        it failed (`FileStorage.fail_interrupted_runs`).
        """
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, context: RunContext) -> None:
        async with self._workspace_locks[context.workspace_id]:
            await self._workflow.run(context)
