import { api } from "../../api/client";

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
}
/** Poll a workspace once for both its sidebar indicator and conversation header. */
export function watchTask(
  workspaceId: string,
  update: (status: TaskStatus) => void,
) {
  const request = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  update({ text: "Loading task…", state: "loading" });
  async function poll() {
    try {
      const runs = await api.listRuns(workspaceId, request.signal);
      const latest =
        runs.find(
          (run) => run.status === "running" || run.status === "queued",
        ) ?? runs[0];
      if (!latest) {
        if (!request.signal.aborted)
          update({ text: "No active task", state: "idle" });
        return;
      }
      const context = { workspaceId, runId: latest.id };
      const [run, result] = await Promise.all([
        api.getRun(context, request.signal),
        api.getEvents(context, 0, request.signal),
      ]);
      if (request.signal.aborted) return;
      const event = result.events.at(-1)?.message;
      const role = run.activeRole
        ? run.activeRole[0].toUpperCase() + run.activeRole.slice(1)
        : "Agent";
      switch (run.status) {
        case "running":
          update({
            state: "running",
            text: `${role} · ${event || "Working…"}`,
          });
          break;
        case "queued":
          update({ state: "queued", text: "Queued · Waiting to start" });
          break;
        case "failed":
          update({
            state: "failed",
            text: `Failed · ${run.error || event || "Run failed"}`,
          });
          break;
        case "completed":
          update({ state: "completed", text: "No active task · Completed" });
          break;
      }
    } catch {
      if (!request.signal.aborted)
        update({ text: "Task status unavailable", state: "unavailable" });
    } finally {
      if (!request.signal.aborted)
        timer = setTimeout(() => {
          void poll();
        }, 3000);
    }
  }
  void poll();
  return () => {
    request.abort();
    clearTimeout(timer);
  };
}
