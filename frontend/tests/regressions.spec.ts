// Author: Ching Kao
// Student ID: 85768427
import { test, expect } from "@playwright/test";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { createHandlers } from "../src/mocks/handlers";

const base = "http://canvas-regression.test/api";
const server = setupServer();
let runId = "run-1",
  status = "completed",
  previewFails = false,
  contentVersion = 1;
const source = "# Source\n\nBlank lines must survive.\n\nLast line\n";
const requests: string[] = [];
test.beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
test.afterAll(() => server.close());
test.beforeEach(async ({ page }) => {
  runId = "run-1";
  status = "completed";
  previewFails = false;
  contentVersion = 1;
  requests.length = 0;
  const summary = () => ({
    id: runId,
    workspaceId: "workspace-1",
    status,
    createdAt: "2026-11-15T00:00:00Z",
  });
  server.resetHandlers(
    http.get(`${base}/workspaces/workspace-1/runs`, () =>
      HttpResponse.json([summary()]),
    ),
    http.get(`${base}/workspaces/workspace-1/runs/:runId`, () =>
      HttpResponse.json({
        ...summary(),
        activeRole: status === "running" ? "coder" : null,
        error: null,
        checks: { build: "not_run", tests: "not_run" },
        usage: { apiCalls: 0, inputTokens: 0, outputTokens: 0, totalTokens: 0 },
      }),
    ),
    http.get(`${base}/workspaces/workspace-1/runs/:runId/events`, () =>
      HttpResponse.json({
        events: [
          {
            id: 1,
            type: status,
            message: `Output ${runId}`,
            createdAt: "2026-11-15T00:00:00Z",
          },
        ],
        nextCursor: 1,
      }),
    ),
    http.get(`${base}/workspaces/workspace-1/runs/:runId/tasks`, () => HttpResponse.json([])),
    http.get(`${base}/workspaces/workspace-1/files`, () =>
      HttpResponse.json([
        { path: "index.html", size: 25, mediaType: "text/html" },
        {
          path: `output-${runId}.md`,
          size: source.length,
          mediaType: "text/plain",
        },
      ]),
    ),
    http.get(
      `${base}/workspaces/workspace-1/file`,
      ({ request }) => {
        const path = new URL(request.url).searchParams.get("path")!;
        if (previewFails && path === "index.html")
          return HttpResponse.json(
            {
              error: {
                code: "TEMPORARY",
                message: "Preview temporarily unavailable",
              },
            },
            { status: 503 },
          );
        return HttpResponse.json({
          path,
          size: 25,
          mediaType: path === "index.html" ? "text/html" : "text/plain",
          encoding: "utf-8",
          content:
            path === "index.html"
              ? `<h1>${runId} version ${contentVersion}</h1>`
              : source,
        });
      },
    ),
    ...createHandlers({ fixtures: { alpha: {}, beta: { "README.md": "# Beta" } }, baseUrl: base, latencyMs: 0 }),
  );
  // The production client makes real HTTP requests; MSW remains the test API boundary.
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    const response = await fetch(
      `http://canvas-regression.test${url.pathname}${url.search}`,
      {
        method: route.request().method(),
        ...(route.request().postData()
          ? { body: route.request().postData() }
          : {}),
      },
    );
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: Buffer.from(await response.arrayBuffer()),
    });
  });
});

test("new runs and completion invalidate artifacts, and reload fetches updated HTML", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-1 version 1",
  );
  runId = "run-2";
  status = "running";
  await expect(
    page.getByRole("button", { name: "output-run-2.md", exact: true }),
  ).toBeVisible({ timeout: 8000 });
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-2 version 1",
  );
  status = "completed";
  contentVersion = 2;
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-2 version 2",
    { timeout: 8000 },
  );
  contentVersion = 3;
  await page
    .getByRole("button", { name: "Reload preview", exact: true })
    .click();
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-2 version 3",
  );
});

test("workspace project files survive a new run and app reload", async ({ page }) => {
  server.use(
    http.get(`${base}/workspaces/workspace-1/files`, () =>
      HttpResponse.json([{ path: "project.md", size: 4, mediaType: "text/plain" }]),
    ),
  );
  await page.goto("/");
  await expect(page.getByRole("button", { name: "project.md" })).toBeVisible();
  runId = "run-2";
  status = "running";
  await expect.poll(() => requests.some(path => path.includes("/runs/run-2/events"))).toBe(true);
  await expect(page.getByRole("button", { name: "project.md" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "project.md" })).toBeVisible();
});

test("automatically loads a newly generated workspace on its isolated origin", async ({ page }) => {
  const previewOrigin = "http://127.0.0.1:15176/";
  let generated = false;
  status = "running";
  server.use(
    http.get(`${base}/workspaces/workspace-1/files`, () =>
      HttpResponse.json(generated ? [{ path: "index.html", size: 25, mediaType: "text/html" }] : []),
    ),
    http.get(`${base}/workspaces/workspace-1/preview`, () => HttpResponse.json({ url: previewOrigin })),
    http.get(`${base}/workspaces/workspace-1/runs/:runId/events`, ({ request }) => {
      const after = Number(new URL(request.url).searchParams.get("after"));
      return HttpResponse.json({
        events: generated && after < 2 ? [{ id: 2, type: "tool_result", message: "coder → writeFile: completed" }] : [],
        nextCursor: generated ? 2 : 1,
      });
    }),
  );
  await page.route(previewOrigin, (route) => route.fulfill({
    contentType: "text/html",
    body: '<h1>Generated app</h1><input aria-label="Scratch"><button id="save">Save</button><p id="status"></p><script type="module" src="app.js"></script>',
  }));
  await page.route(`${previewOrigin}app.js`, (route) => route.fulfill({
    contentType: "text/javascript",
    body: `
      const status = document.getElementById('status');
      status.textContent = localStorage.getItem('playlist') ?? 'Ready';
      document.getElementById('save').onclick = () => {
        localStorage.setItem('playlist', 'Saved playlist');
        status.textContent = 'Saved playlist';
      };
    `,
  }));
  await page.goto("/");
  await expect(page.locator(".preview-address")).toHaveText("No preview connected");
  generated = true;
  const frame = page.frameLocator("iframe");
  await expect(frame.getByText("Ready")).toBeVisible({ timeout: 8000 });
  await expect(page.locator("iframe")).toHaveAttribute("sandbox", /allow-same-origin/);
  const input = frame.getByRole("textbox", { name: "Scratch" });
  await input.fill("Keep this while the run finishes");
  await frame.getByRole("button", { name: "Save" }).click();
  const previewRequests = requests.filter(path => path.endsWith("/preview")).length;
  status = "completed";
  await expect.poll(
    () => requests.filter(path => path.endsWith("/preview")).length,
  ).toBeGreaterThan(previewRequests);
  await expect(page.locator(".preview-address")).toHaveText(previewOrigin);
  await expect(input).toHaveValue("Keep this while the run finishes");
  await page.getByRole("button", { name: "Reload preview" }).click();
  await expect(frame.getByText("Saved playlist")).toBeVisible();
  await expect(input).toBeEmpty();
});

test("rejects a backend-issued preview on the Canvas origin", async ({ page }) => {
  server.use(http.get(`${base}/workspaces/workspace-1/preview`, () =>
    HttpResponse.json({ url: "http://127.0.0.1:14175/" }),
  ));
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Project preview must use a separate local origin.");
  await expect(page.locator("iframe")).toHaveCount(0);
});

test("index.html failure preserves other files and permits independent retry", async ({
  page,
}) => {
  previewFails = true;
  await page.goto("/");
  await expect(page.getByRole("alert")).toHaveText(
    "Preview temporarily unavailableRetry",
  );
  await page
    .getByRole("button", { name: "output-run-1.md", exact: true })
    .click();
  const code = page.locator(".file-dialog code");
  await expect(code).toContainText("Blank lines must survive.");
  await expect(page.locator('pre[data-language="markdown"]')).toBeVisible();
  const copied = await code.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    return selection.toString();
  });
  expect(copied).toBe(source);
  await page.keyboard.press("Escape");
  previewFails = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-1 version 1",
  );
});

test("page lifecycle resumes polling and discovers new work after restoration", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".task-message .task-title")).toHaveText("Completed");
  await page.evaluate(() =>
    window.dispatchEvent(
      new PageTransitionEvent("pagehide", { persisted: true }),
    ),
  );
  runId = "run-after-restore";
  status = "running";
  await page.evaluate(() =>
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    ),
  );
  await expect.poll(() => requests.some(path => path.includes("/runs/run-after-restore/events"))).toBe(true);
  await expect(page.frameLocator("iframe").getByRole("heading")).toHaveText(
    "run-after-restore version 1",
  );
});
