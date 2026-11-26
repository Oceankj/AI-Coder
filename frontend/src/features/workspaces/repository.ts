// Author: Ching Kao
// Student ID: 85768427
import { api } from "../../api/client";
import type { CanvasWorkspace, WorkspaceFile } from "./model";
export type WorkspaceArtifacts = Pick<
  CanvasWorkspace,
  "source" | "files" | "runId" | "runStatus" | "automaticPreviewUrl" | "previewHtml" | "previewError"
>;

function isolatedPreviewUrl(value: string): string {
  const url = new URL(value);
  const backend = new URL(import.meta.env?.VITE_API_BASE_URL || "/api", location.href);
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    url.origin === location.origin ||
    url.origin === backend.origin ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("Project preview must use a separate local origin.");
  }
  return url.href;
}

export async function loadWorkspaceArtifacts(
  id: string,
  signal: AbortSignal,
): Promise<WorkspaceArtifacts> {
  const [detail, runs, listedFiles] = await Promise.all([
    api.getWorkspace(id, signal),
    api.listRuns(id, signal),
    api.listFiles(id, signal),
  ]);
  const run = runs[0];
  const files: WorkspaceFile[] = listedFiles.map(
    (file) => ({
      path: file.path,
      size: file.size,
      read: async (readSignal) => {
        const response = await api.readFile(id, file.path, readSignal);
        return new Blob([response.content], { type: response.mediaType });
      },
    }),
  );
  let automaticPreviewUrl: string | undefined;
  let previewHtml: string | undefined, previewError: string | undefined;
  const entry = files.find((file) => file.path === "index.html");
  if (entry) {
    try {
      const { url } = await api.getWorkspacePreview(id, signal);
      if (url !== null) automaticPreviewUrl = isolatedPreviewUrl(url);
      // Offline fixtures can still embed their self-contained HTML.
      else if (entry.size <= 2 * 1024 * 1024)
        previewHtml = await (await entry.read(signal)).text();
    } catch (error) {
      if (signal.aborted) throw error;
      previewError =
        error instanceof Error
          ? error.message
          : "Could not load project preview.";
    }
  }
  return {
    source: detail.rootPath,
    files,
    runId: run?.id,
    runStatus: run?.status,
    automaticPreviewUrl,
    previewHtml,
    previewError,
  };
}
