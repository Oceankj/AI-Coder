import { http, HttpResponse, delay } from "msw";
import type { GenerationInput } from "../../types";
import type { MockRun } from "../store";
import { apiError, notFound, findRun, type HandlerOptions } from "./shared";

const summary = ({ id, workspaceId, status, createdAt }: MockRun["detail"]) =>
  ({ id, workspaceId, status, createdAt });

export function createRunHandlers({ store, baseUrl, latencyMs }: HandlerOptions) {
  return [
    http.get(`${baseUrl}/workspaces/:workspaceId/runs`, async ({ params }) => {
      await delay(latencyMs);
      const workspace = store.get(String(params.workspaceId));
      return workspace
        ? HttpResponse.json(workspace.runs.map((run) => summary(run.detail)))
        : notFound();
    }),
    http.post(
      `${baseUrl}/workspaces/:workspaceId/runs`,
      async ({ params, request }) => {
        const workspace = store.get(String(params.workspaceId));
        if (!workspace) return notFound();
        const body = (await request
          .json()
          .catch(() => null)) as GenerationInput | null;
        if (
          !body ||
          typeof body.description !== "string" ||
          !body.description.trim() ||
          !Array.isArray(body.requirements) ||
          !body.requirements.every((item) => typeof item === "string")
        )
          return apiError(
            400,
            "INVALID_INPUT",
            "Provide a description string and a requirements array of strings.",
          );
        const createdAt = new Date().toISOString();
        const run: MockRun = {
          detail: {
            id: crypto.randomUUID(),
            workspaceId: workspace.detail.id,
            status: "queued",
            createdAt,
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
              type: "queued",
              message:
                "Request queued in MSW; agent execution is not simulated.",
              createdAt,
            },
          ],
          files: {},
        };
        workspace.runs.unshift(run);
        return HttpResponse.json(summary(run.detail), { status: 201 });
      },
    ),
    http.get(
      `${baseUrl}/workspaces/:workspaceId/runs/:runId`,
      async ({ params }) => {
        await delay(latencyMs);
        const run = findRun(store, params.workspaceId, params.runId);
        return run ? HttpResponse.json(run.detail) : notFound();
      },
    ),
    http.get(
      `${baseUrl}/workspaces/:workspaceId/runs/:runId/events`,
      ({ params, request }) => {
        const run = findRun(store, params.workspaceId, params.runId);
        if (!run) return notFound();
        const after = Number(
          new URL(request.url).searchParams.get("after") ?? 0,
        );
        if (!Number.isSafeInteger(after) || after < 0)
          return apiError(
            400,
            "INVALID_CURSOR",
            "after must be a nonnegative integer.",
          );
        return HttpResponse.json({
          events: run.events.filter((event) => event.id > after),
          nextCursor: Math.max(after, run.events.at(-1)?.id ?? 0),
        });
      },
    ),
  ];
}
