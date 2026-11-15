import "./styles.css";
import { button, element, icon } from "./ui";
import {
  workspaceFromSummary,
  loadWorkspace,
  type CanvasWorkspace,
} from "./features/workspaces/model";
import { workspaceTree } from "./features/workspaces";
import { createWorkspaceDialog } from "./features/workspaces/create";
import { createFilePreview } from "./features/artifacts";
import { createChatPanel } from "./features/generation";

import { api } from "./api/client";

const workspaces: CanvasWorkspace[] = [];
let active: CanvasWorkspace | undefined;
let selectionRequest: AbortController | undefined;
const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <div class="app-layout">
    <aside class="sidebar" id="workspace-sidebar" aria-label="Workspaces"><div class="sidebar-heading"><h1>Workspaces</h1><div id="sidebar-actions"></div></div><p class="sidebar-caption">A space for every idea.</p><div id="workspace-list"></div><button class="workspace-action" id="create-workspace" type="button">＋ Create workspace</button></aside>
    <main class="main"><header class="canvas-toolbar"><div class="breadcrumb"><span id="sidebar-toggle"></span><span class="muted">Workspace</span><span class="breadcrumb-slash">/</span><strong id="active-name"></strong></div><span class="canvas-label">CANVAS</span></header>
      <section class="canvas-stage" aria-label="Project preview"><div class="preview-window"><div class="preview-toolbar"><div class="preview-tab"></div><div class="preview-address"></div><div class="preview-actions"></div></div><div class="preview-body"></div></div><footer class="canvas-footer"><span id="workspace-source"></span><span>A place for your ideas to take shape.</span></footer></section>
    </main>
  </div>
  <dialog class="form-dialog url-dialog" aria-labelledby="url-title"><form id="url-form"><div class="dialog-header"><h2 id="url-title">Connect project UI</h2><button type="button" id="close-url" class="icon-button" aria-label="Close settings">×</button></div><p>Start your project, then enter its development server URL.</p><label for="preview-url">Preview URL</label><input id="preview-url" type="url" placeholder="http://localhost:3000" required autofocus /><p class="field-hint">Use an HTTP or HTTPS URL that allows iframe embedding. Storage and sign-in may be limited in the sandbox.</p><p id="url-error" role="alert"></p><button type="submit" class="primary-button">Connect preview</button></form></dialog>
  <div id="notice" class="notice" role="status"></div>`;
const get = <T extends HTMLElement>(selector: string) =>
  document.querySelector<T>(selector)!;
const openFile = createFilePreview();
let chat: ReturnType<typeof createChatPanel> | undefined;
const sidebarToggle = button("Collapse Workspaces", "panel");
sidebarToggle.setAttribute("aria-controls", "workspace-sidebar");
sidebarToggle.setAttribute("aria-expanded", "true");
get("#sidebar-toggle").append(sidebarToggle);
let sidebarCollapsed = window.innerWidth <= 560;
function updateSidebar() {
  app.classList.toggle("sidebar-collapsed", sidebarCollapsed);
  get("#workspace-sidebar").hidden = sidebarCollapsed;
  sidebarToggle.setAttribute("aria-expanded", String(!sidebarCollapsed));
  sidebarToggle.setAttribute(
    "aria-label",
    sidebarCollapsed ? "Expand Workspaces" : "Collapse Workspaces",
  );
  sidebarToggle.title = sidebarCollapsed
    ? "Expand Workspaces"
    : "Collapse Workspaces";
}
updateSidebar();
sidebarToggle.onclick = () => {
  sidebarCollapsed = !sidebarCollapsed;
  updateSidebar();
};
const openCreateWorkspace = createWorkspaceDialog((summary) => {
  const workspace =
    workspaces.find((item) => item.id === summary.id) ??
    workspaceFromSummary(summary);
  if (!workspaces.includes(workspace)) workspaces.push(workspace);
  void selectWorkspace(workspace);
  announce(`Created ${workspace.name}.`);
}, announce);
const add = button("Create workspace", "plus");
get("#sidebar-actions").append(add);
add.onclick = openCreateWorkspace;
get("#create-workspace").onclick = openCreateWorkspace;
let noticeTimer: ReturnType<typeof setTimeout>;
function announce(text: string) {
  get("#notice").textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    get("#notice").textContent = "";
  }, 6000);
}
const expanded = new Set<string>();
function renderWorkspaces() {
  const list = get("#workspace-list");
  list.replaceChildren();
  for (const workspace of workspaces) {
    const section = element(
      "section",
      `workspace ${workspace.id === active?.id ? "active" : ""}`,
    );
    const row = element("div", "workspace-row");
    const toggle = button(
      `${expanded.has(workspace.id) ? "Collapse" : "Expand"} ${workspace.name}`,
      "chevron",
    );
    toggle.classList.add("workspace-chevron");
    toggle.setAttribute("aria-expanded", String(expanded.has(workspace.id)));
    const select = button(workspace.name, "folder", "workspace-select");
    if (workspace.id === active?.id)
      select.setAttribute("aria-current", "true");
    select.append(
      element("span", "workspace-count", String(workspace.files.length)),
    );
    select.onclick = () => selectWorkspace(workspace);
    const tree = workspaceTree(workspace, (file) => {
      void openFile(file, workspace.name);
    });
    if (workspace.loading)
      tree.append(element("li", "file-row", "Loading files…"));
    else if (workspace.error)
      tree.append(
        element("li", "file-row", "Could not load. Select workspace to retry."),
      );
    else if (workspace.loaded && !workspace.files.length)
      tree.append(element("li", "file-row", "No generated files yet"));
    tree.id = `files-${workspace.id}`;
    tree.hidden = !expanded.has(workspace.id);
    toggle.setAttribute("aria-controls", tree.id);
    toggle.onclick = () => {
      if (!expanded.has(workspace.id) && !workspace.loaded) {
        void selectWorkspace(workspace);
        return;
      }
      if (expanded.has(workspace.id)) expanded.delete(workspace.id);
      else expanded.add(workspace.id);
      tree.hidden = !expanded.has(workspace.id);
      toggle.setAttribute("aria-expanded", String(!tree.hidden));
      const label = `${tree.hidden ? "Expand" : "Collapse"} ${workspace.name}`;
      toggle.setAttribute("aria-label", label);
      toggle.title = label;
    };
    row.append(toggle, select);
    section.append(row, tree);
    list.append(section);
  }
}
const previewTab = get(".preview-tab");
previewTab.append(icon("monitor"), element("span", "", "Live preview"));
const address = get(".preview-address");
const connect = button("Set preview URL", "code");
const reload = button("Reload preview", "refresh");
const external = button("Open in new tab", "external");
get(".preview-actions").append(connect, reload, external);
const urlDialog = get<HTMLDialogElement>(".url-dialog");
const urlInput = get<HTMLInputElement>("#preview-url");
connect.onclick = () => {
  if (!active) return;
  urlInput.value = active.previewUrl ?? "";
  get("#url-error").textContent = "";
  urlDialog.showModal();
};
get("#close-url").onclick = () => urlDialog.close();
get<HTMLFormElement>("#url-form").onsubmit = (event) => {
  event.preventDefault();
  try {
    const url = new URL(urlInput.value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      throw new Error();
    if (
      url.origin === window.location.origin &&
      url.pathname === window.location.pathname
    ) {
      get("#url-error").textContent =
        "Enter a project URL instead of the Canvas URL.";
      return;
    }
    if (!active) return;
    active.previewUrl = url.href;
    urlDialog.close();
    renderPreview();
  } catch {
    get("#url-error").textContent = "Enter a valid HTTP or HTTPS URL.";
  }
};
function renderPreview() {
  const body = get(".preview-body");
  body.replaceChildren();
  connect.disabled = !active;
  if (!active || active.loading || active.error) {
    address.textContent = active?.loading ? "Loading…" : "No preview connected";
    reload.disabled = true;
    external.disabled = true;
    const state = element("div", "preview-empty");
    state.setAttribute("role", active?.error ? "alert" : "status");
    state.append(
      element(
        "p",
        "",
        active?.error ||
          (active?.loading
            ? "Loading workspace and files…"
            : "Select or create a workspace to get started."),
      ),
    );
    if (active?.error) {
      const retry = button("Retry", "refresh", "primary-button");
      retry.onclick = () => {
        if (active) void selectWorkspace(active);
      };
      state.append(retry);
    }
    body.append(state);
    return;
  }
  address.textContent =
    active?.previewUrl ||
    (active?.previewHtml
      ? `${active.name} / index.html`
      : "No preview connected");
  address.title = address.textContent;
  external.disabled = !active?.previewUrl;
  reload.disabled = !active?.previewUrl && !active?.previewHtml;
  if (active?.previewUrl || active?.previewHtml) {
    const frame = element("iframe");
    frame.title = `${active.name} project UI`;
    frame.setAttribute("sandbox", "allow-scripts allow-forms allow-downloads");
    frame.referrerPolicy = "no-referrer";
    if (active?.previewUrl) frame.src = active?.previewUrl;
    else frame.srcdoc = active?.previewHtml!;
    body.append(frame);
    if (active?.previewUrl) {
      const hint = element(
        "div",
        "embed-hint",
        "Blank preview? Check that your project is running and allows iframe embedding, or use Open in new tab.",
      );
      body.append(hint);
    }
  } else {
    const empty = element("div", "preview-empty");
    const mark = element("div", "empty-mark");
    mark.append(icon("monitor"));
    empty.append(
      mark,
      element("span", "eyebrow", "A SPACE FOR YOUR NEXT IDEA"),
      element("h2", "", "Bring your project to life"),
      element(
        "p",
        "",
        "Browse your files or connect a project URL\nto preview it right here.",
      ),
    );
    const start = button("Connect project UI", "plus", "primary-button");
    start.onclick = () => connect.click();
    empty.append(start);
    body.append(empty);
  }
}
reload.onclick = renderPreview;
external.onclick = () => {
  if (active?.previewUrl)
    window.open(active?.previewUrl, "_blank", "noopener,noreferrer");
};
async function selectWorkspace(workspace: CanvasWorkspace) {
  selectionRequest?.abort();
  if (active?.loading) active.loading = false;
  const request = new AbortController();
  selectionRequest = request;
  active = workspace;
  expanded.add(workspace.id);
  get("#active-name").textContent = workspace.name;
  if (chat) chat.selectWorkspace(workspace);
  else chat = createChatPanel(workspace);
  workspace.error = undefined;
  workspace.loading = !workspace.loaded;
  get("#workspace-source").textContent = workspace.source;
  renderWorkspaces();
  renderPreview();
  if (workspace.loaded) return;
  try {
    const data = await loadWorkspace(workspace.id, request.signal);
    if (request.signal.aborted || active !== workspace) return;
    Object.assign(workspace, data, { loaded: true });
  } catch (error) {
    if (request.signal.aborted || active !== workspace) return;
    workspace.error =
      error instanceof Error ? error.message : "Could not load workspace.";
  } finally {
    if (!request.signal.aborted && active === workspace) {
      workspace.loading = false;
      get("#workspace-source").textContent = workspace.source;
      renderWorkspaces();
      renderPreview();
    }
  }
}
async function loadWorkspaces() {
  const list = get("#workspace-list");
  list.replaceChildren(element("p", "file-row", "Loading workspaces…"));
  try {
    const summaries = await api.listWorkspaces();
    for (const summary of summaries) {
      if (!workspaces.some((workspace) => workspace.id === summary.id))
        workspaces.push(workspaceFromSummary(summary));
    }
    // Creation can finish while the initial list request is still pending.
    if (!active && workspaces.length) await selectWorkspace(workspaces[0]);
    else renderWorkspaces();
    if (!workspaces.length)
      list.append(
        element(
          "p",
          "file-row",
          "No workspaces yet. Create one to get started.",
        ),
      );
  } catch (error) {
    renderWorkspaces();
    const message = element(
      "p",
      "file-row",
      error instanceof Error ? error.message : "Could not load workspaces.",
    );
    message.setAttribute("role", "alert");
    const retry = button(
      "Retry loading workspaces",
      "refresh",
      "workspace-action",
    );
    retry.onclick = () => {
      void loadWorkspaces();
    };
    list.append(message, retry);
  }
}
renderPreview();
void loadWorkspaces();
