import type { RunStatus, WorkspaceSummary } from "../../types";
import type { TaskStatus } from "../generation/task-status";
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
  loading?: boolean;
  error?: string;
  taskStatus?: TaskStatus;
  runId?: string;
  runStatus?: RunStatus;
  previewHtml?: string;
  previewError?: string;
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
