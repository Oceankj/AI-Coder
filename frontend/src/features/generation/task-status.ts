import { api } from "../../api/client";
import { startPolling } from "../../core/poll";
import type { RunDetail, RunSummary } from "../../types";
export interface TaskStatus {
  text: string;
  state:
    | "loading"
    | "idle"
    | "queued"
    | "running"
    | "completed"
    | "failed"
    | "unavailable";
  latestRun?: RunSummary;
}
export function describeTask(run: RunDetail, message?: string): TaskStatus {
  const role = run.activeRole
    ? run.activeRole[0].toUpperCase() + run.activeRole.slice(1)
    : "Agent";
  switch (run.status) {
    case "running":
      return { state: "running", text: `${role} · ${message || "Working…"}` };
    case "queued":
      return { state: "queued", text: "Queued · Waiting to start" };
    case "failed":
      return {
        state: "failed",
        text: `Failed · ${run.error || message || "Run failed"}`,
      };
    case "completed":
      return { state: "completed", text: "No active task · Completed" };
  }
}
/** A cursor belongs to a run. Terminal runs are cached; list polling still discovers new work. */
export function watchTask(
  workspaceId: string,
  update: (status: TaskStatus) => void,
  options: { client?: typeof api; interval?: number } = {},
) {
  const client = options.client ?? api;
  let currentId: string | undefined;
  let cursor = 0,
    message: string | undefined,
    terminal: RunDetail | undefined;
  update({ state: "loading", text: "Loading task…" });
  return startPolling(
    async (signal) => {
      const runs = await client.listRuns(workspaceId, signal);
      const selected =
        runs.find(
          (run) => run.status === "running" || run.status === "queued",
        ) ?? runs[0];
      const latestRun = runs[0];
      if (!selected) {
        if (!signal.aborted) update({ state: "idle", text: "No active task" });
        return;
      }
      if (selected.id !== currentId) {
        currentId = selected.id;
        cursor = 0;
        message = undefined;
        terminal = undefined;
      }
      const isTerminal =
        selected.status === "completed" || selected.status === "failed";
      if (terminal?.status === selected.status && isTerminal) {
        if (!signal.aborted)
          update({ ...describeTask(terminal, message), latestRun });
        return;
      }
      const context = { workspaceId, runId: selected.id };
      const [run, result] = await Promise.all([
        client.getRun(context, signal),
        client.getEvents(context, cursor, signal),
      ]);
      if (signal.aborted) return;
      cursor = result.nextCursor;
      message = result.events.at(-1)?.message ?? message;
      terminal =
        run.status === "completed" || run.status === "failed" ? run : undefined;
      update({ ...describeTask(run, message), latestRun });
    },
    () => update({ state: "unavailable", text: "Task status unavailable" }),
    options.interval,
  );
}
