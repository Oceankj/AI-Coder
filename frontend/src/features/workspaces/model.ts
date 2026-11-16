import { api } from "../../api/client";
import type { TaskStatus } from "../generation/task-status";
import type { WorkspaceSummary } from "../../types";
export interface WorkspaceFile {
  path: string;
  size: number;
  read: (signal?: AbortSignal) => Promise<Blob>;
}
export interface CanvasWorkspace {
  id: string;
  name: string;
  source: string;
  files: WorkspaceFile[];
  loaded: boolean;
  taskStatus?: TaskStatus;
  loading?: boolean;
  error?: string;
  previewHtml?: string;
  previewUrl?: string;
  messages: string[];
  draft: string;
}
export function workspaceFromSummary(
  summary: WorkspaceSummary,
): CanvasWorkspace {
  return {
    ...summary,
    source: "",
    files: [],
    loaded: false,
    messages: [],
    draft: "",
  };
}
export async function loadWorkspace(id: string, signal: AbortSignal) {
  const [detail, runs] = await Promise.all([
    api.getWorkspace(id, signal),
    api.listRuns(id, signal),
  ]);
  const run = runs[0];
  if (!run)
    return {
      source: detail.rootPath,
      files: [] as WorkspaceFile[],
      previewHtml: undefined,
    };
  const context = { workspaceId: id, runId: run.id };
  const files = (await api.listFiles(context, signal)).map((file) => ({
    path: file.path,
    size: file.size,
    read: async (readSignal?: AbortSignal) => {
      const response = await api.readFile(context, file.path, readSignal);
      return new Blob([response.content], { type: response.mediaType });
    },
  }));
  const entry = files.find(
    (file) => file.path === "index.html" && file.size <= 2 * 1024 * 1024,
  );
  const previewHtml = entry
    ? await (await entry.read(signal)).text()
    : undefined;
  return { source: detail.rootPath, files, previewHtml };
}
