// Author: Ching Kao
// Student ID: 85768427
import type { ChatMessage, RunStatus, WorkspaceSummary } from "../../types";
import type { TaskStatus } from "../generation/task-status";
import type { TaskNotice } from "../generation/history";
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
  chatRunId?: string;
  runStatus?: RunStatus;
  automaticPreviewUrl?: string;
  previewHtml?: string;
  previewError?: string;
  previewUrl?: string;
  messages: ChatMessage[];
  notices: TaskNotice[];
  draft: string;
  chatCleared?: boolean;
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
    notices: [],
    draft: "",
  };
}
