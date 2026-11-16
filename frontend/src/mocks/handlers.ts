import { http, HttpResponse, delay } from "msw";
import { zipSync, strToU8 } from "fflate";
import { createMockStore } from "./store";
import type { MockRun } from "./store";
import type { GenerationInput } from "../types";

export function createHandlers(
  fixtures: Record<string, Record<string, string>>,
  baseUrl = "/api",
  latency = 120,
) {
  const store = createMockStore(fixtures);
  const base = baseUrl.replace(/\/$/, "");
  const error = (status: number, code: string, message: string) =>
    HttpResponse.json({ error: { code, message } }, { status });
  const notFound = () =>
    error(404, "NOT_FOUND", "Workspace, run, or file not found.");
  const metadata = (path: string, content: string) => ({
    path,
    size: new TextEncoder().encode(content).byteLength,
    mediaType: path.endsWith(".html")
      ? "text/html"
      : path.endsWith(".json")
        ? "application/json"
        : "text/plain",
  });
  const findRun = (workspaceId: unknown, runId: unknown) =>
    store.get(String(workspaceId))?.runs.find((run) => run.detail.id === runId);
  const summary = ({
    id,
    workspaceId,
    status,
    createdAt,
  }: MockRun["detail"]) => ({ id, workspaceId, status, createdAt });
  return [
    http.get(`${base}/workspaces`, async () => {
      await delay(latency);
      return HttpResponse.json(
        [...store.values()].map(({ detail: { id, name } }) => ({ id, name })),
      );
    }),
    http.post(`${base}/workspaces`, async ({ request }) => {
      const body = (await request.json().catch(() => null)) as {
        name?: unknown;
      } | null;
      if (typeof body?.name !== "string" || !body.name.trim())
        return error(400, "INVALID_INPUT", "name must be a nonempty string.");
      const id = crypto.randomUUID();
      const name = body.name.trim();
      store.set(id, {
        detail: {
          id,
          name,
          rootPath: `workspaces/${id}`,
          createdAt: new Date().toISOString(),
        },
        runs: [],
      });
      return HttpResponse.json({ id, name }, { status: 201 });
    }),
    http.get(`${base}/workspaces/:workspaceId`, async ({ params }) => {
      await delay(latency);
      const workspace = store.get(String(params.workspaceId));
      return workspace ? HttpResponse.json(workspace.detail) : notFound();
    }),
    http.get(`${base}/workspaces/:workspaceId/runs`, async ({ params }) => {
      await delay(latency);
      const workspace = store.get(String(params.workspaceId));
      return workspace
        ? HttpResponse.json(workspace.runs.map((run) => summary(run.detail)))
        : notFound();
    }),
    http.post(
      `${base}/workspaces/:workspaceId/runs`,
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
          return error(
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
      `${base}/workspaces/:workspaceId/runs/:runId`,
      async ({ params }) => {
        await delay(latency);
        const run = findRun(params.workspaceId, params.runId);
        return run ? HttpResponse.json(run.detail) : notFound();
      },
    ),
    http.get(
      `${base}/workspaces/:workspaceId/runs/:runId/events`,
      ({ params, request }) => {
        const run = findRun(params.workspaceId, params.runId);
        if (!run) return notFound();
        const after = Number(
          new URL(request.url).searchParams.get("after") ?? 0,
        );
        if (!Number.isSafeInteger(after) || after < 0)
          return error(
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
    http.get(
      `${base}/workspaces/:workspaceId/runs/:runId/files`,
      async ({ params }) => {
        await delay(latency);
        const run = findRun(params.workspaceId, params.runId);
        return run
          ? HttpResponse.json(
              Object.entries(run.files).map(([path, content]) =>
                metadata(path, content),
              ),
            )
          : notFound();
      },
    ),
    http.get(
      `${base}/workspaces/:workspaceId/runs/:runId/file`,
      async ({ params, request }) => {
        await delay(latency);
        const run = findRun(params.workspaceId, params.runId);
        if (!run) return notFound();
        const path = new URL(request.url).searchParams.get("path");
        if (
          !path ||
          path.startsWith("/") ||
          path.includes("\\") ||
          path.includes("\0") ||
          /^[a-z]:/i.test(path) ||
          path.split("/").some((segment) => ["..", ".", ""].includes(segment))
        )
          return error(
            400,
            "INVALID_PATH",
            "Provide a valid project-relative path.",
          );
        if (!Object.hasOwn(run.files, path)) return notFound();
        const content = run.files[path];
        const file = metadata(path, content);
        if (file.size > 2 * 1024 * 1024)
          return error(
            413,
            "FILE_TOO_LARGE",
            "File exceeds the 2 MB preview limit.",
          );
        return HttpResponse.json({ ...file, content, encoding: "utf-8" });
      },
    ),
    http.get(
      `${base}/workspaces/:workspaceId/runs/:runId/download`,
      ({ params }) => {
        const run = findRun(params.workspaceId, params.runId);
        if (!run) return notFound();
        if (run.detail.status !== "completed")
          return error(409, "NOT_READY", "Run is not complete yet.");
        const archive = zipSync(
          Object.fromEntries(
            Object.entries(run.files).map(([path, content]) => [
              path,
              strToU8(content),
            ]),
          ),
        );
        return new HttpResponse(new Uint8Array(archive).buffer, {
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": `attachment; filename="${run.detail.id}.zip"`,
          },
        });
      },
    ),
  ];
}
