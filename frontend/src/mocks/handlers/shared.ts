// Author: Ching Kao
// Student ID: 85768427
import { HttpResponse } from "msw";
import type { MockWorkspace } from "../store";

export interface HandlerOptions {
  store: Map<string, MockWorkspace>;
  baseUrl: string;
  latencyMs: number;
}

export function apiError(status: number, code: string, message: string) {
  return HttpResponse.json({ error: { code, message } }, { status });
}

export function notFound() {
  return apiError(404, "NOT_FOUND", "Workspace, run, or file not found.");
}

export function findRun(store: HandlerOptions["store"], workspaceId: unknown, runId: unknown) {
  return store.get(String(workspaceId))?.runs.find(run => run.detail.id === runId);
}
