// Author: Ching Kao
// Student ID: 85768427
import type { WorkspaceDetail, RunDetail, RunEvent } from "../types";
export interface MockRun {
  detail: RunDetail;
  events: RunEvent[];
}
export interface MockWorkspace {
  detail: WorkspaceDetail;
  runs: MockRun[];
  files: Record<string, string>;
}
export function createMockStore(
  fixtures: Record<string, Record<string, string>>,
) {
  // Fixtures only seed the server. IDs, file metadata, creates and lookups are stateful.
  const now = new Date().toISOString();
  return new Map<string, MockWorkspace>(
    Object.entries(fixtures).map(([name, files], index) => {
      const id = `workspace-${index + 1}`;
      const run: MockRun = {
        detail: {
          id: `run-${index + 1}`,
          workspaceId: id,
          status: "completed",
          createdAt: now,
          activeRole: null,
          error: null,
          checks: { build: "not_run", tests: "not_run" },
          usage: {
            apiCalls: 0,
            inputTokens: 0,
            outputTokens: 0,
            totalTokens: 0,
          },
        },
        events: [
          {
            id: 1,
            type: "completed",
            message: "MSW fixture loaded; no agents or checks were executed.",
            createdAt: now,
          },
        ],
      };
      return [
        id,
        {
          detail: { id, name, rootPath: `workspaces/${id}`, createdAt: now },
          runs: [run],
          files,
        },
      ];
    }),
  );
}
