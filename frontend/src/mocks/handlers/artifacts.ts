import { http, HttpResponse, delay } from "msw";
import { zipSync, strToU8 } from "fflate";
import { apiError, notFound, findRun, type HandlerOptions } from "./shared";

function fileMetadata(path: string, content: string) {
  return {
    path,
    size: new TextEncoder().encode(content).byteLength,
    mediaType: path.endsWith(".html") ? "text/html" : path.endsWith(".json") ? "application/json" : "text/plain",
  };
}

export function createArtifactHandlers({ store, baseUrl, latencyMs }: HandlerOptions) {
  return [
    http.get(
      `${baseUrl}/workspaces/:workspaceId/runs/:runId/files`,
      async ({ params }) => {
        await delay(latencyMs);
        const run = findRun(store, params.workspaceId, params.runId);
        return run
          ? HttpResponse.json(
              Object.entries(run.files).map(([path, content]) =>
                fileMetadata(path, content),
              ),
            )
          : notFound();
      },
    ),
    http.get(
      `${baseUrl}/workspaces/:workspaceId/runs/:runId/file`,
      async ({ params, request }) => {
        await delay(latencyMs);
        const run = findRun(store, params.workspaceId, params.runId);
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
          return apiError(
            400,
            "INVALID_PATH",
            "Provide a valid project-relative path.",
          );
        if (!Object.hasOwn(run.files, path)) return notFound();
        const content = run.files[path];
        const file = fileMetadata(path, content);
        if (file.size > 2 * 1024 * 1024)
          return apiError(
            413,
            "FILE_TOO_LARGE",
            "File exceeds the 2 MB preview limit.",
          );
        return HttpResponse.json({ ...file, content, encoding: "utf-8" });
      },
    ),
    http.get(
      `${baseUrl}/workspaces/:workspaceId/runs/:runId/download`,
      ({ params }) => {
        const run = findRun(store, params.workspaceId, params.runId);
        if (!run) return notFound();
        if (run.detail.status !== "completed")
          return apiError(409, "NOT_READY", "Run is not complete yet.");
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
