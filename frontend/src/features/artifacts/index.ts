import { button, element, icon } from "../../ui";
import type { WorkspaceFile } from "../workspaces/model";
export function createFilePreview(): (
  file: WorkspaceFile,
  workspaceName: string,
) => Promise<void> {
  const dialog = element("dialog", "file-dialog");
  dialog.setAttribute("aria-labelledby", "file-title");
  const header = element("header", "dialog-header");
  const title = element("h2", "", "File preview");
  title.id = "file-title";
  const close = button("Close preview", "close");
  close.autofocus = true;
  close.onclick = () => dialog.close();
  header.append(icon("file"), title, close);
  const meta = element("p", "file-meta");
  const content = element("div", "file-content");
  dialog.append(header, meta, content);
  document.body.append(dialog);
  let revision = 0;
  let request: AbortController | undefined;
  dialog.addEventListener("close", () => {
    revision++;
    request?.abort();
  });
  return async (file, workspaceName) => {
    const current = ++revision;
    request?.abort();
    request = new AbortController();
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
      if (revision !== current) return;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      if (revision !== current) return;
      let text: string;
      try {
        if (bytes.includes(0)) throw new Error("binary");
        text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        content.textContent =
          "This is a binary or non-UTF-8 file. Open it in a local application.";
        return;
      }
      const pre = element("pre");
      pre.append(element("code", "", text || "(Empty file)"));
      content.replaceChildren(pre);
    } catch (error) {
      if (revision === current)
        content.textContent =
          error instanceof Error
            ? `Could not read file: ${error.message}`
            : "Could not read file. Please try again.";
    }
  };
}
