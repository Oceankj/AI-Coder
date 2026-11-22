/** Wire contract documented in docs/interfaces.md (camelCase JSON). */
export interface RunContext {
  workspaceId: string;
  runId: string;
}
export interface WorkspaceSummary {
  id: string;
  name: string;
}
export interface WorkspaceDetail extends WorkspaceSummary {
  rootPath: string;
  createdAt: string;
}
export type RunStatus = "blocked" | "queued" | "running" | "completed" | "failed";
export interface RunSummary {
  id: string;
  workspaceId: string;
  status: RunStatus;
  createdAt: string;
}
export interface RunDetail extends RunSummary {
  coordinatorReport?: string;
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
  role?: "planner" | "tester" | "coder" | "coordinator";
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
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
export interface ChatConfig {
  configured: boolean;
  model: string;
}
export interface ChatReply {
  status?: RunStatus;
  runId?: string;
  message: ChatMessage;
  model: string;
  resolvedModel?: string;
  timing?: { providerMs: number; adapterMs: number };
  usage: {
    apiCalls: number;
    inputTokens: number | null;
    outputTokens: number | null;
    totalTokens: number | null;
  };
}
export interface AICallRecord {
  callId: string;
  requestId: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  event: "started" | "completed" | "failed" | "cancelled";
  caller: "chat" | "agent";
  role: string | null;
  model: string | null;
  resolvedModel: string | null;
  status: number | null;
  providerStatus: number | null;
  durationMs: number | null;
  providerMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  errorCode: string | null;
}
