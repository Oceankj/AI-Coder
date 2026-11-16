import type {
  WorkspaceSummary,
  WorkspaceDetail,
  RunContext,
  GenerationInput,
  RunSummary,
  RunDetail,
  RunEvents,
  ArtifactFile,
  FileContent,
  ApiErrorBody,
} from "../types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
/** No fixtures or mock branches: the same requests work against MSW and HTTP. */
export function createApiClient(baseUrl = "/api") {
  const base = baseUrl.replace(/\/$/, "");
  const workspacePath = (id: string) => `/workspaces/${encodeURIComponent(id)}`;
  const runPath = (context: RunContext) =>
    `${workspacePath(context.workspaceId)}/runs/${encodeURIComponent(context.runId)}`;
  async function request(path: string, signal?: AbortSignal, body?: unknown) {
    const response = await fetch(`${base}${path}`, {
      signal,
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      const error = (await response
        .json()
        .catch(() => null)) as ApiErrorBody | null;
      throw new ApiError(
        response.status,
        error?.error?.code ?? "HTTP_ERROR",
        error?.error?.message ?? `API request failed (${response.status})`,
      );
    }
    return response;
  }
  async function json<T>(
    path: string,
    signal?: AbortSignal,
    body?: unknown,
  ): Promise<T> {
    const response = await request(path, signal, body);
    if (!response.headers.get("content-type")?.includes("application/json"))
      throw new ApiError(
        response.status,
        "INVALID_RESPONSE",
        "The API did not return JSON. Check the backend URL and /api routes.",
      );
    return response.json() as Promise<T>;
  }
  return {
    listWorkspaces: (signal?: AbortSignal) =>
      json<WorkspaceSummary[]>("/workspaces", signal),
    createWorkspace: (name: string, signal?: AbortSignal) =>
      json<WorkspaceSummary>("/workspaces", signal, { name }),
    getWorkspace: (id: string, signal?: AbortSignal) =>
      json<WorkspaceDetail>(workspacePath(id), signal),
    listRuns: (id: string, signal?: AbortSignal) =>
      json<RunSummary[]>(`${workspacePath(id)}/runs`, signal),
    createRun: (id: string, input: GenerationInput, signal?: AbortSignal) =>
      json<RunSummary>(`${workspacePath(id)}/runs`, signal, input),
    getRun: (context: RunContext, signal?: AbortSignal) =>
      json<RunDetail>(runPath(context), signal),
    getEvents: (context: RunContext, after = 0, signal?: AbortSignal) =>
      json<RunEvents>(`${runPath(context)}/events?after=${after}`, signal),
    listFiles: (context: RunContext, signal?: AbortSignal) =>
      json<ArtifactFile[]>(`${runPath(context)}/files`, signal),
    readFile: (context: RunContext, path: string, signal?: AbortSignal) =>
      json<FileContent>(
        `${runPath(context)}/file?${new URLSearchParams({ path })}`,
        signal,
      ),
    download: async (context: RunContext, signal?: AbortSignal) =>
      (await request(`${runPath(context)}/download`, signal)).blob(),
  };
}
export const api = createApiClient(
  import.meta.env?.VITE_API_BASE_URL || "/api",
);
