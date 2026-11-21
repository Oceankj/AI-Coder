import { http, HttpResponse, delay } from "msw";
import { apiError, notFound, type HandlerOptions } from "./shared";

export function createWorkspaceHandlers({ store, baseUrl, latencyMs }: HandlerOptions) {
  return [
    http.get(`${baseUrl}/workspaces`, async () => {
      await delay(latencyMs);
      return HttpResponse.json(
        [...store.values()].map(({ detail: { id, name } }) => ({ id, name })),
      );
    }),
    http.post(`${baseUrl}/workspaces`, async ({ request }) => {
      const body = (await request.json().catch(() => null)) as {
        name?: unknown;
      } | null;
      if (typeof body?.name !== "string" || !body.name.trim())
        return apiError(400, "INVALID_INPUT", "name must be a nonempty string.");
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
    http.get(`${baseUrl}/workspaces/:workspaceId`, async ({ params }) => {
      await delay(latencyMs);
      const workspace = store.get(String(params.workspaceId));
      return workspace ? HttpResponse.json(workspace.detail) : notFound();
    }),
  ];
}
