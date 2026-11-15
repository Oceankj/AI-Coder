/** Wire contract documented in docs/interfaces.md (camelCase JSON). */
export interface RunContext {
  workspaceId: string;
  runId: string;
}
export interface GenerationInput {
  description: string;
  requirements: string[];
}
export interface WorkspaceSummary {
  id: string;
  name: string;
}
export interface WorkspaceDetail extends WorkspaceSummary {
  rootPath: string;
  createdAt: string;
}
export type RunStatus = "queued" | "running" | "completed" | "failed";
export interface RunSummary {
  id: string;
  workspaceId: string;
  status: RunStatus;
  createdAt: string;
}
export interface RunDetail extends RunSummary {
  activeRole: "planner" | "coder" | "tester" | null;
  error: string | null;
  checks: {
    build: "not_run" | "passed" | "failed";
    tests: "not_run" | "passed" | "failed";
  };
  usage: {
    apiCalls: number;
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
  };
}
export interface RunEvent {
  id: number;
  type: string;
  message: string;
  createdAt: string;
}
export interface RunEvents {
  events: RunEvent[];
  nextCursor: number;
}
export interface ArtifactFile {
  path: string;
  size: number;
  mediaType: string;
}
export interface FileContent extends ArtifactFile {
  content: string;
  encoding: "utf-8";
}
export interface ApiErrorBody {
  error: { code: string; message: string };
}
