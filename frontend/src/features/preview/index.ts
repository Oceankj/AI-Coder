// Author: Ching Kao
// Student ID: 85768427
import { button, element, icon } from "../../ui";
import { createInputDialog } from "../../components/input-dialog";
import { stateView } from "../../components/feedback";
import type { CanvasWorkspace } from "../workspaces/model";
export function createProjectPreview(root: HTMLElement, refresh: () => void) {
  let workspace: CanvasWorkspace | undefined;
  let reloadWorkspace: CanvasWorkspace | undefined;
  let embedded:
    | { workspace: CanvasWorkspace; url?: string; html?: string; sandbox: string }
    | undefined;
  const toolbar = element("div", "preview-toolbar");
  const tab = element("div", "preview-tab");
  tab.append(icon("monitor"), element("span", "", "Live preview"));
  const address = element("div", "preview-address");
  const actions = element("div", "preview-actions");
  const connect = button("Set preview URL", "code"),
    reload = button("Reload preview", "refresh"),
    external = button("Open in new tab", "external");
  actions.append(connect, reload, external);
  toolbar.append(tab, address, actions);
  const body = element("div", "preview-body");
  root.append(toolbar, body);
  const connection = createInputDialog({
    id: "preview-url",
    title: "Connect project UI",
    closeLabel: "Close settings",
    label: "Preview URL",
    placeholder: "http://localhost:3000",
    type: "url",
    className: "url-dialog",
    description: "Start your project, then enter its development server URL.",
    hint: "Use an HTTP or HTTPS URL that allows iframe embedding. Storage and sign-in may be limited in the sandbox.",
    submitLabel: "Connect preview",
    validate: (value) => {
      try {
        const url = new URL(value);
        if (
          !["http:", "https:"].includes(url.protocol) ||
          url.username ||
          url.password
        )
          return "Enter a valid HTTP or HTTPS URL.";
        if (
          url.origin === location.origin &&
          url.pathname === location.pathname
        )
          return "Enter a project URL instead of the Canvas URL.";
      } catch {
        return "Enter a valid HTTP or HTTPS URL.";
      }
    },
    submit: (value) => new URL(value).href,
    onSuccess: (url) => {
      if (workspace) {
        workspace.previewUrl = url;
        render(workspace);
      }
    },
  });
  connect.onclick = () => {
    if (workspace) connection.open(workspace.previewUrl);
  };
  reload.onclick = () => {
    reloadWorkspace = workspace;
    refresh();
  };
  external.onclick = () => {
    const url = workspace?.previewUrl ?? workspace?.automaticPreviewUrl;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };
  function render(next?: CanvasWorkspace) {
    workspace = next;
    const previewUrl = next?.previewUrl ?? next?.automaticPreviewUrl;
    // Only the backend-issued isolated origin may keep its own storage.
    const sandbox = next?.automaticPreviewUrl && !next.previewUrl
      ? "allow-scripts allow-forms allow-downloads allow-same-origin"
      : "allow-scripts allow-forms allow-downloads";
    connect.disabled = !next;
    address.textContent = next?.loading
      ? "Loading…"
      : previewUrl ||
        (next?.previewHtml
          ? `${next.name} / index.html`
          : "No preview connected");
    address.title = address.textContent;
    reload.disabled = !next || !!next.loading;
    external.disabled = !previewUrl;
    if (embedded && embedded.workspace === next && !next.error) {
      if (next.loading) return;
      if (
        reloadWorkspace !== next &&
        embedded.url === previewUrl &&
        embedded.html === next.previewHtml &&
        embedded.sandbox === sandbox
      ) return;
    }
    if (reloadWorkspace === next) reloadWorkspace = undefined;
    embedded = undefined;
    body.replaceChildren();
    if (!next || next.loading || next.error) {
      body.append(
        stateView(
          next?.error ||
            (next?.loading
              ? "Loading workspace and files…"
              : "Select or create a workspace to get started."),
          { error: !!next?.error, retry: next?.error ? refresh : undefined },
        ),
      );
      return;
    }
    if (previewUrl || next.previewHtml) {
      const frame = element("iframe");
      frame.title = `${next.name} project UI`;
      frame.setAttribute("sandbox", sandbox);
      frame.referrerPolicy = "no-referrer";
      if (previewUrl) frame.src = previewUrl;
      else frame.srcdoc = next.previewHtml!;
      body.append(frame);
      embedded = { workspace: next, url: previewUrl, html: next.previewHtml, sandbox };
      if (next.previewUrl)
        body.append(
          element(
            "div",
            "embed-hint",
            "Blank preview? Check that your project is running and allows iframe embedding, or use Open in new tab.",
          ),
        );
    } else if (next.previewError) {
      body.append(
        stateView(next.previewError, { error: true, retry: refresh }),
      );
    } else {
      const empty = element("div", "preview-empty"),
        mark = element("div", "empty-mark");
      mark.append(icon("monitor"));
      const start = button("Connect project UI", "plus", "primary-button");
      start.onclick = () => connect.click();
      empty.append(
        mark,
        element("span", "eyebrow", "A SPACE FOR YOUR NEXT IDEA"),
        element("h2", "", "Bring your project to life"),
        element(
          "p",
          "",
          "Browse your files or connect a project URL\nto preview it right here.",
        ),
        start,
      );
      body.append(empty);
    }
  }
  return { render };
}
