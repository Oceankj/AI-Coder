// Author: Ching Kao
// Student ID: 85768427
import { button, element, icon } from "../../ui";
import { createInputDialog } from "../../components/input-dialog";
import { stateView } from "../../components/feedback";
import type { CanvasWorkspace } from "../workspaces/model";
import { mountPreviewDocument } from "./document";
export function createProjectPreview(root: HTMLElement, refresh: () => void) {
  let workspace: CanvasWorkspace | undefined;
  let cleanupStorage = () => {};
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
  reload.onclick = refresh;
  external.onclick = () => {
    if (workspace?.previewUrl)
      window.open(workspace.previewUrl, "_blank", "noopener,noreferrer");
  };
  function render(next?: CanvasWorkspace) {
    workspace = next;
    cleanupStorage();
    cleanupStorage = () => {};
    body.replaceChildren();
    connect.disabled = !next;
    address.textContent = next?.loading
      ? "Loading…"
      : next?.previewUrl ||
        (next?.previewHtml
          ? `${next.name} / index.html`
          : "No preview connected");
    address.title = address.textContent;
    reload.disabled = !next || !!next.loading;
    external.disabled = !next?.previewUrl;
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
    if (next.previewUrl || next.previewHtml) {
      const frame = element("iframe");
      frame.title = `${next.name} project UI`;
      frame.setAttribute(
        "sandbox",
        "allow-scripts allow-forms allow-downloads",
      );
      frame.referrerPolicy = "no-referrer";
      if (next.previewUrl) frame.src = next.previewUrl;
      else {
        try {
          cleanupStorage = mountPreviewDocument(frame, next.previewHtml!, next.id);
        } catch {
          body.append(stateView("Could not initialize preview storage. Check browser storage permissions.", { error: true }));
          return;
        }
      }
      body.append(frame);
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
