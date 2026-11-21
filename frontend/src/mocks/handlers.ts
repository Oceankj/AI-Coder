import { createMockStore } from "./store";
import { createChatHandlers } from "./handlers/chat";
import { createWorkspaceHandlers } from "./handlers/workspaces";
import { createRunHandlers } from "./handlers/runs";
import { createArtifactHandlers } from "./handlers/artifacts";

interface MockApiOptions {
  fixtures: Record<string, Record<string, string>>;
  baseUrl?: string;
  latencyMs?: number;
}

/** One fresh store per mock API; all route groups share it. */
export function createHandlers({
  fixtures,
  baseUrl = "/api",
  latencyMs = 120,
}: MockApiOptions) {
  const options = {
    store: createMockStore(fixtures),
    baseUrl: baseUrl.replace(/\/$/, ""),
    latencyMs,
  };
  return [
    ...createChatHandlers(options),
    ...createWorkspaceHandlers(options),
    ...createRunHandlers(options),
    ...createArtifactHandlers(options),
  ];
}
