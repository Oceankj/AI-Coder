import { test, expect } from "@playwright/test";
import { setupServer } from "msw/node";
import { http, HttpResponse, delay } from "msw";
import { unzipSync, strFromU8 } from "fflate";
import { createHandlers } from "../src/mocks/handlers";
import { createApiClient } from "../src/api/client";
const base = "http://canvas-api.test/api";
const server = setupServer();
const api = createApiClient(base);
test.beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
test.beforeEach(() =>
  server.resetHandlers(
    ...createHandlers({
      fixtures: {
        alpha: {
          "docs/hello world.md": "# Hello",
          "index.html": "<h1>Alpha</h1>",
        },
        beta: { "README.md": "# Beta" },
      },
      baseUrl: base,
      latencyMs: 0,
    }),
  ),
);
test.afterAll(() => server.close());

test("chat mocks require a real backend instead of retaining keys or inventing replies", async () => {
  expect(await api.chatConfig()).toMatchObject({ configured: false });
  await expect(api.configureChat("test-only-key")).rejects.toMatchObject({
    status: 503, code: "CHAT_REQUIRES_BACKEND",
  });
  await expect(api.chat([{ role: "user", content: "Hello" }])).rejects.toMatchObject({
    status: 503, code: "CHAT_REQUIRES_BACKEND",
  });
  expect(await api.chatConfig()).toMatchObject({ configured: false });
});

test("workspace and run creates persist through the documented read routes", async () => {
  const before = await api.listWorkspaces();
  const workspace = await api.createWorkspace("New project");
  expect((await api.listWorkspaces()).length).toBe(before.length + 1);
  expect(await api.getWorkspace(workspace.id)).toMatchObject(workspace);
  expect(await api.listRuns(workspace.id)).toEqual([]);
  const run = await api.createRun(workspace.id, {
    description: "Build a timer",
    requirements: ["Keyboard accessible"],
  });
  const context = { workspaceId: workspace.id, runId: run.id };
  expect(await api.listRuns(workspace.id)).toEqual([run]);
  expect(await api.getRun(context)).toMatchObject({
    status: "queued",
    activeRole: null,
    checks: { build: "not_run", tests: "not_run" },
    usage: { totalTokens: 0 },
  });
  const first = await api.getEvents(context);
  expect(first.events).toHaveLength(1);
  expect(await api.getEvents(context, first.nextCursor)).toEqual({
    events: [],
    nextCursor: first.nextCursor,
  });
  expect(await api.listFiles(context)).toEqual([]);
  await expect(api.download(context)).rejects.toMatchObject({
    status: 409,
    code: "NOT_READY",
  });
});

test("file content, metadata, and downloaded archive agree", async () => {
  const [workspace] = await api.listWorkspaces();
  const [run] = await api.listRuns(workspace.id);
  const context = { workspaceId: workspace.id, runId: run.id };
  const files = await api.listFiles(context);
  const file = await api.readFile(context, "docs/hello world.md");
  expect(file).toMatchObject({
    path: "docs/hello world.md",
    content: "# Hello",
    encoding: "utf-8",
    size: 7,
  });
  expect(files.find((item) => item.path === file.path)?.size).toBe(file.size);
  const zip = await api.download(context);
  expect(zip.type).toBe("application/zip");
  const unpacked = unzipSync(new Uint8Array(await zip.arrayBuffer()));
  expect(strFromU8(unpacked[file.path])).toBe(file.content);
});

test("rejects mismatched workspace/run pairs, traversal, missing files, and invalid input", async () => {
  const [a, b] = await api.listWorkspaces();
  const [run] = await api.listRuns(a.id);
  const context = { workspaceId: a.id, runId: run.id };
  await expect(
    api.listFiles({ workspaceId: b.id, runId: run.id }),
  ).rejects.toMatchObject({ status: 404 });
  for (const path of [
    "../secret",
    "/etc/passwd",
    "C:/secret",
    "docs/../secret",
    "docs\\secret",
  ]) {
    await expect(api.readFile(context, path)).rejects.toMatchObject({
      status: 400,
      code: "INVALID_PATH",
    });
  }
  await expect(api.readFile(context, "missing.md")).rejects.toMatchObject({
    status: 404,
  });
  await expect(api.createWorkspace("  ")).rejects.toMatchObject({
    status: 400,
  });
  await expect(
    api.createRun(a.id, { description: "", requirements: [] }),
  ).rejects.toMatchObject({ status: 400 });
  await expect(api.getEvents(context, -1)).rejects.toMatchObject({
    status: 400,
  });
});

test("client propagates aborts, server errors, and invalid backend responses", async () => {
  server.use(
    http.get(`${base}/workspaces`, async () => {
      await delay(100);
      return HttpResponse.json([]);
    }),
  );
  const controller = new AbortController();
  const pending = api.listWorkspaces(controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  server.use(
    http.get(`${base}/workspaces`, () =>
      HttpResponse.json(
        { error: { code: "UNAVAILABLE", message: "Try later" } },
        { status: 503 },
      ),
    ),
  );
  await expect(api.listWorkspaces()).rejects.toMatchObject({
    status: 503,
    message: "Try later",
  });
  server.use(
    http.get(`${base}/workspaces`, () =>
      HttpResponse.html("<html>Vite fallback</html>"),
    ),
  );
  await expect(api.listWorkspaces()).rejects.toMatchObject({
    code: "INVALID_RESPONSE",
  });
});
