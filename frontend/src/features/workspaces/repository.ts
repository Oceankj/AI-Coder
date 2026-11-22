// Author: Ching Kao
// Student ID: 85768427
import { api } from "../../api/client";
import type { CanvasWorkspace, WorkspaceFile } from "./model";
export type WorkspaceArtifacts = Pick<
  CanvasWorkspace,
  "source" | "files" | "runId" | "runStatus" | "previewHtml" | "previewError"
>;
export async function loadWorkspaceArtifacts(
  id: string,
  signal: AbortSignal,
): Promise<WorkspaceArtifacts> {
  const [detail, runs] = await Promise.all([
    api.getWorkspace(id, signal),
    api.listRuns(id, signal),
  ]);
  const run = runs[0];
  if (!run)
    return {
      source: detail.rootPath,
      files: [],
      runId: undefined,
      runStatus: undefined,
      previewHtml: undefined,
      previewError: undefined,
    };
  const context = { workspaceId: id, runId: run.id };
  const files: WorkspaceFile[] = (await api.listFiles(context, signal)).map(
    (file) => ({
      path: file.path,
      size: file.size,
      read: async (readSignal) => {
        const response = await api.readFile(context, file.path, readSignal);
        return new Blob([response.content], { type: response.mediaType });
      },
    }),
  );
  let previewHtml: string | undefined, previewError: string | undefined;
  const entry = files.find(
    (file) => file.path === "index.html" && file.size <= 2 * 1024 * 1024,
  );
  if (entry) {
    try {
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
    runId: run.id,
    runStatus: run.status,
    previewHtml,
    previewError,
  };
}
