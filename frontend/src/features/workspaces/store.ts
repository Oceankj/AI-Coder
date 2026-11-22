import { api } from "../../api/client";
import { latestRequest } from "../../core/latest-request";
import { watchTask } from "../generation/task-status";
import type { WorkspaceSummary, RunSummary } from "../../types";
import { workspaceFromSummary, type CanvasWorkspace } from "./model";
import { loadWorkspaceArtifacts } from "./repository";

type Change = {
  type: "list" | "selection" | "artifacts" | "task";
  workspace?: CanvasWorkspace;
};
/** Owns server reads, cache invalidation and lifecycle; views never schedule API work. */
export function createWorkspaceStore() {
  const workspaces: CanvasWorkspace[] = [];
  let active: CanvasWorkspace | undefined,
    listLoading = false,
    listError: string | undefined,
    paused = false;
  const listeners = new Set<(change: Change) => void>();
  const listRequest = latestRequest(),
    artifactRequest = latestRequest();
  const watchers = new Map<string, () => void>();
  const observedRuns = new Map<string, string>();
  const emit = (type: Change["type"], workspace?: CanvasWorkspace) => {
    for (const listener of listeners) listener({ type, workspace });
  };
  const version = (run?: RunSummary) => (run ? `${run.id}:${run.status}` : "");
  function watch(workspace: CanvasWorkspace) {
    if (paused || watchers.has(workspace.id)) return;
    const stop = watchTask(workspace.id, (status) => {
      workspace.taskStatus = status;
      emit("task", workspace);
      if (status.state === "unavailable" || status.state === "loading") return;
      const previous = observedRuns.get(workspace.id),
        next = version(status.latestRun);
      observedRuns.set(workspace.id, next);
      // First poll can race the initial artifact load. Later changes cancel stale loads.
      if (previous !== undefined && previous !== next) {
        workspace.loaded = false;
        if (active === workspace) void refresh();
      } else if (
        workspace.loaded &&
        (workspace.runId !== status.latestRun?.id ||
          workspace.runStatus !== status.latestRun?.status)
      ) {
        workspace.loaded = false;
        if (active === workspace) void refresh();
      }
    }, { chatRunId: () => workspace.chatRunId });
    watchers.set(workspace.id, stop);
  }
  async function refresh() {
    if (!active || paused) return;
    const workspace = active,
      request = artifactRequest.start();
    workspace.loading = true;
    workspace.error = undefined;
    emit("artifacts", workspace);
    try {
      const data = await loadWorkspaceArtifacts(workspace.id, request.signal);
      if (!request.isCurrent() || active !== workspace) return;
      Object.assign(workspace, data, { loaded: true });
    } catch (error) {
      if (!request.isCurrent() || active !== workspace) return;
      workspace.error =
        error instanceof Error ? error.message : "Could not load workspace.";
    } finally {
      if (request.isCurrent() && active === workspace) {
        workspace.loading = false;
        emit("artifacts", workspace);
      }
    }
  }
  function select(workspace: CanvasWorkspace) {
    artifactRequest.cancel();
    if (active) active.loading = false;
    active = workspace;
    emit("selection", workspace);
    // Always revalidate on selection; never assume a workspace's run is permanent.
    void refresh();
  }
  function add(summary: WorkspaceSummary) {
    let workspace = workspaces.find((item) => item.id === summary.id);
    if (!workspace) {
      workspace = workspaceFromSummary(summary);
      workspaces.push(workspace);
    }
    emit("list");
    watch(workspace);
    return workspace;
  }
  async function load() {
    const request = listRequest.start();
    listLoading = true;
    listError = undefined;
    emit("list");
    try {
      const summaries = await api.listWorkspaces(request.signal);
      if (!request.isCurrent()) return;
      for (const summary of summaries) {
        if (!workspaces.some((workspace) => workspace.id === summary.id))
          workspaces.push(workspaceFromSummary(summary));
      }
      emit("list");
      for (const workspace of workspaces) watch(workspace);
      if (!active && workspaces.length) select(workspaces[0]);
    } catch (error) {
      if (request.isCurrent())
        listError =
          error instanceof Error ? error.message : "Could not load workspaces.";
    } finally {
      if (request.isCurrent()) {
        listLoading = false;
        emit("list");
      }
    }
  }
  function pause() {
    paused = true;
    listRequest.cancel();
    artifactRequest.cancel();
    if (active) active.loading = false;
    for (const stop of watchers.values()) stop();
    watchers.clear();
  }
  function resume() {
    if (!paused) return;
    paused = false;
    for (const workspace of workspaces) watch(workspace);
    if (listLoading || !active) void load();
    if (active) void refresh();
  }
  return {
    get state() {
      return { workspaces, active, listLoading, listError };
    },
    subscribe(listener: (change: Change) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    select,
    add,
    load,
    refresh,
    pause,
    resume,
  };
}
export type WorkspaceStore = ReturnType<typeof createWorkspaceStore>;
