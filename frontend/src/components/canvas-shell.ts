// Author: Ching Kao
// Student ID: 85768427
import { button } from "../ui";
export function createCanvasShell(root: HTMLElement) {
  root.innerHTML = `
    <div class="app-layout">
      <aside class="sidebar" id="workspace-sidebar" aria-label="Workspaces"><div class="sidebar-heading"><h1>Workspaces</h1><div id="sidebar-actions"></div></div><p class="sidebar-caption">A space for every idea.</p><div id="workspace-list"></div><button class="workspace-action" id="create-workspace" type="button">＋ Create workspace</button></aside>
      <main class="main"><header class="canvas-toolbar"><div class="breadcrumb"><span id="sidebar-toggle"></span><span class="muted">Workspace</span><span class="breadcrumb-slash">/</span><strong id="active-name"></strong></div><span class="canvas-label">CANVAS</span></header>
        <section class="canvas-stage" aria-label="Project preview"><div class="preview-window"></div><footer class="canvas-footer"><span id="workspace-source"></span><span>A place for your ideas to take shape.</span></footer></section>
      </main>
    </div>`;
  const get = (selector: string) => root.querySelector<HTMLElement>(selector)!;
  const toggle = button("Collapse Workspaces", "panel");
  toggle.setAttribute("aria-controls", "workspace-sidebar");
  get("#sidebar-toggle").append(toggle);
  let collapsed = innerWidth <= 560;
  const update = () => {
    root.classList.toggle("sidebar-collapsed", collapsed);
    get("#workspace-sidebar").hidden = collapsed;
    toggle.setAttribute("aria-expanded", String(!collapsed));
    const text = `${collapsed ? "Expand" : "Collapse"} Workspaces`;
    toggle.setAttribute("aria-label", text);
    toggle.title = text;
  };
  toggle.onclick = () => {
    collapsed = !collapsed;
    update();
  };
  update();
  return {
    list: get("#workspace-list"),
    preview: get(".preview-window"),
    actions: get("#sidebar-actions"),
    create: get("#create-workspace"),
    name: get("#active-name"),
    source: get("#workspace-source"),
  };
}
