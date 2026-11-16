import { button, element, icon } from "../../ui";
import { fileLanguage } from "./languages";
import type { WorkspaceFile } from "../workspaces/model";
export function createFilePreview(): (
  file: WorkspaceFile,
  workspaceName: string,
) => Promise<void> {
  const dialog = element("dialog", "file-dialog");
  dialog.setAttribute("aria-labelledby", "file-title");
  dialog.setAttribute("closedby", "any");
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    // Safari fallback: require both ends outside so text-selection drags stay open.
    const outside = (event: PointerEvent) => {
      const bounds = dialog.getBoundingClientRect();
      return event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom;
    };
    let pressedOutside = false;
    dialog.addEventListener("pointerdown", event => { pressedOutside = outside(event); });
    dialog.addEventListener("pointerup", event => {
      if (pressedOutside && outside(event)) dialog.close();
      pressedOutside = false;
    });
    dialog.addEventListener("pointercancel", () => { pressedOutside = false; });
  }
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
      pre.tabIndex = 0;
      pre.setAttribute("aria-label", "File source");
      const code = element("code", "", text || "(Empty file)");
      pre.append(code);
      content.replaceChildren(pre);
      const language = fileLanguage(file.path);
      // Bound expensive tokenization/DOM work independently of the API's 2 MB limit.
      const canHighlight =
        language &&
        bytes.length <= 100 * 1024 &&
        text.split("\n").length <= 3000;
      if (!canHighlight || !text) return;
      try {
        const { highlightCode } = await import("./highlight");
        if (revision !== current) return;
        const result = await highlightCode(text, language);
        if (revision !== current) return;
        const fragment = document.createDocumentFragment();
        result.tokens.forEach((tokens, index) => {
          const line = element("span", "source-line");
          line.dataset.line = String(index + 1);
          const gutter = element("span", "source-gutter");
          gutter.dataset.line = String(index + 1);
          gutter.setAttribute("aria-hidden", "true");
          line.append(gutter);
          // textContent keeps HTML/script source inert. Never insert source as HTML.
          for (const token of tokens) {
            const span = element("span", "", token.content);
            if (token.color) span.style.color = token.color;
            if (token.fontStyle) {
              if (token.fontStyle & 1) span.style.fontStyle = "italic";
              if (token.fontStyle & 2) span.style.fontWeight = "bold";
              if (token.fontStyle & 4) span.style.textDecoration = "underline";
            }
            line.append(span);
          }
          fragment.append(line);
          if (index < result.tokens.length - 1)
            fragment.append(document.createTextNode("\n"));
        });
        code.replaceChildren(fragment);
        pre.classList.add("highlighted-source");
        pre.dataset.language = language;
        pre.style.backgroundColor = result.bg || "";
        pre.style.color = result.fg || "";
      } catch {
        // The already-rendered plaintext remains usable if a grammar/chunk fails.
      }
    } catch (error) {
      if (revision === current)
        content.textContent =
          error instanceof Error
            ? `Could not read file: ${error.message}`
            : "Could not read file. Please try again.";
    }
  };
}
