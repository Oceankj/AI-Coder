import { element } from "../../ui";
import { createDialog } from "../../components/dialog";
import { latestRequest } from "../../core/latest-request";
import { renderSource } from "./source-view";
import type { WorkspaceFile } from "../workspaces/model";
export function createFilePreview(): (
  file: WorkspaceFile,
  workspaceName: string,
) => Promise<void> {
  const { dialog, title, close } = createDialog({
    id: "file-title",
    title: "File preview",
    closeLabel: "Close preview",
    className: "file-dialog",
    icon: "file",
    lightDismiss: true,
  });
  close.autofocus = true;
  const meta = element("p", "file-meta"),
    content = element("div", "file-content");
  dialog.append(meta, content);
  const requests = latestRequest();
  dialog.addEventListener("close", requests.cancel);
  return async (file, workspaceName) => {
    const request = requests.start();
    title.textContent = file.path.split("/").at(-1)!;
    meta.textContent = `${workspaceName} / ${file.path} · ${new Intl.NumberFormat().format(file.size)} bytes · Read-only`;
    content.textContent = "Loading…";
    dialog.showModal();
    if (file.size > 2 * 1024 * 1024) {
      content.textContent =
        "This file exceeds 2 MB. Open it in your local editor.";
      return;
    }
    try {
      const blob = await file.read(request.signal);
      if (!request.isCurrent()) return;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      if (!request.isCurrent()) return;
      let source: string;
      try {
        if (bytes.includes(0)) throw new Error("binary");
        source = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        content.textContent =
          "This is a binary or non-UTF-8 file. Open it in a local application.";
        return;
      }
      await renderSource(content, source, file.path, request.isCurrent);
    } catch (error) {
      if (request.isCurrent())
        content.textContent =
          error instanceof Error
            ? `Could not read file: ${error.message}`
            : "Could not read file. Please try again.";
    }
  };
}
