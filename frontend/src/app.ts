// Author: Ching Kao
// Student ID: 85768427
import "./styles.css";
import { button } from "./ui";
import { createCanvasShell } from "./components/canvas-shell";
import { createNotice } from "./components/feedback";
import { createWorkspaceStore } from "./features/workspaces/store";
import { createWorkspaceSidebar } from "./features/workspaces/sidebar";
import { createWorkspaceDialog } from "./features/workspaces/create";
import { createFilePreview } from "./features/artifacts";
import { createProjectPreview } from "./features/preview";
import { createChatPanel } from "./features/generation";

const shell = createCanvasShell(
  document.querySelector<HTMLDivElement>("#app")!,
);
const store = createWorkspaceStore();
const announce = createNotice();
const openFile = createFilePreview();
const preview = createProjectPreview(shell.preview, () => {
  void store.refresh();
});
const sidebar = createWorkspaceSidebar(
  shell.list,
  store.select,
  (file, workspace) => {
    void openFile(file, workspace.name);
  },
  () => {
    void store.load();
  },
  announce,
);
const chat = createChatPanel();
const openCreate = createWorkspaceDialog((summary) => {
  const workspace = store.add(summary);
  store.select(workspace);
  announce(`Created ${workspace.name}.`);
}, announce);
const add = button("Create workspace", "plus");
add.onclick = openCreate;
shell.actions.append(add);
shell.create.onclick = openCreate;
store.subscribe((change) => {
  const { active } = store.state;
  if (change.type === "task" && change.workspace) {
    sidebar.updateTask(change.workspace);
    if (active === change.workspace)
      chat?.updateTask(change.workspace.taskStatus!);
    return;
  }
  if (change.type === "selection" && active) {
    sidebar.expand(active.id);
    chat.selectWorkspace(active);
  }
  sidebar.render(store.state);
  if (change.type !== "list") {
    shell.name.textContent = active?.name ?? "";
    shell.source.textContent = active?.source ?? "";
    preview.render(active);
  }
});
window.addEventListener("pagehide", store.pause);
window.addEventListener("pageshow", store.resume);
preview.render();
void store.load();
