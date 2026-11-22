// Author: Ching Kao
// Student ID: 85768427
import { test, expect } from "@playwright/test";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { createApiClient } from "../src/api/client";
import {
  watchTask,
  type TaskStatus,
} from "../src/features/generation/task-status";
const base = "http://task-status.test/api";
const server = setupServer();
test.beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
test.afterAll(() => server.close());

test("polls events incrementally, retains the last message, stops terminal reads and resets new-run cursors", async () => {
  let id = "first",
    state = "running";
  const cursors: { id: string; after: number }[] = [];
  const statuses: TaskStatus[] = [];
  server.resetHandlers(
    http.get(`${base}/workspaces/alpha/runs`, () =>
      HttpResponse.json([
        { id, workspaceId: "alpha", status: state, createdAt: "" },
      ]),
    ),
    http.get(`${base}/workspaces/alpha/runs/:id`, () =>
      HttpResponse.json({
        id,
        workspaceId: "alpha",
        status: state,
        activeRole: "coder",
        error: null,
      }),
    ),
    http.get(
      `${base}/workspaces/alpha/runs/:id/events`,
      ({ request, params }) => {
        const after = Number(new URL(request.url).searchParams.get("after"));
        cursors.push({ id: String(params.id), after });
        return HttpResponse.json({
          events: after === 0 ? [{ id: 2, message: "Writing files" }] : [],
          nextCursor: 2,
        });
      },
    ),
    http.get(`${base}/workspaces/alpha/runs/:id/tasks`, () => HttpResponse.json([])),
  );
  const stop = watchTask("alpha", (status) => statuses.push(status), {
    client: createApiClient(base),
    interval: 25,
  });
  try {
    await expect.poll(() => cursors.length).toBeGreaterThan(2);
    expect(cursors[0]).toEqual({ id: "first", after: 0 });
    expect(cursors.slice(1).every((cursor) => cursor.after === 2)).toBe(true);
    expect(statuses.at(-1)?.text).toBe("Coder is working…");
    state = "completed";
    await expect.poll(() => statuses.at(-1)?.state).toBe("completed");
    const count = cursors.length,
      updateCount = statuses.length;
    await expect.poll(() => statuses.length).toBeGreaterThan(updateCount + 2);
    expect(cursors.length).toBe(count);
    id = "second";
    state = "running";
    await expect
      .poll(() => cursors.some((cursor) => cursor.id === "second"))
      .toBe(true);
    expect(cursors.find((cursor) => cursor.id === "second")).toEqual({
      id: "second",
      after: 0,
    });
  } finally {
    stop();
  }
});
