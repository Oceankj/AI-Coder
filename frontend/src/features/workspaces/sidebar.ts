import { button, element } from "../../ui";
import { workspaceTree } from "./index";
import type { CanvasWorkspace, WorkspaceFile } from "./model";
import type { WorkspaceStore } from "./store";
export function createWorkspaceSidebar(
  root: HTMLElement,
  select: (workspace: CanvasWorkspace) => void,
  openFile: (file: WorkspaceFile, workspace: CanvasWorkspace) => void,
  retry: () => void,
) {
  const expanded = new Set<string>();
  const indicators = new Map<string, HTMLElement>();
  function updateTask(workspace: CanvasWorkspace) {
    const indicator = indicators.get(workspace.id);
    if (!indicator) return;
    indicator.hidden = !["queued", "running"].includes(
      workspace.taskStatus?.state ?? "",
    );
    indicator.title = workspace.taskStatus?.text ?? "";
  }
  function render(state: WorkspaceStore["state"]) {
    const focused =
      document.activeElement instanceof HTMLElement &&
      root.contains(document.activeElement)
        ? document.activeElement.dataset.focusKey
        : undefined;
    root.replaceChildren();
    indicators.clear();
    for (const workspace of state.workspaces) {
      const section = element(
        "section",
        `workspace ${workspace === state.active ? "active" : ""}`,
      );
      const row = element("div", "workspace-row");
      const toggle = button("", "chevron");
      toggle.classList.add("workspace-chevron");
      toggle.dataset.focusKey = `toggle-${workspace.id}`;
      const choose = button(workspace.name, "folder", "workspace-select");
      choose.dataset.focusKey = `select-${workspace.id}`;
      if (workspace === state.active)
        choose.setAttribute("aria-current", "true");
      choose.onclick = () => {
        expanded.add(workspace.id);
        select(workspace);
      };
      const indicator = element("span", "workspace-loader");
      indicator.setAttribute("role", "status");
      indicator.setAttribute(
        "aria-label",
        `Task in progress for ${workspace.name}`,
      );
      indicators.set(workspace.id, indicator);
      updateTask(workspace);
      const tree = workspaceTree(workspace, (file) =>
        openFile(file, workspace),
      );
      tree.id = `files-${workspace.id}`;
      if (workspace.loading)
        tree.append(element("li", "file-row", "Loading files…"));
      else if (workspace.error)
        tree.append(
          element(
            "li",
            "file-row",
            "Could not load. Select workspace to retry.",
          ),
        );
      else if (workspace.loaded && !workspace.files.length)
        tree.append(element("li", "file-row", "No generated files yet"));
      const setExpanded = () => {
        tree.hidden = !expanded.has(workspace.id);
        toggle.setAttribute("aria-expanded", String(!tree.hidden));
        const label = `${tree.hidden ? "Expand" : "Collapse"} ${workspace.name}`;
        toggle.setAttribute("aria-label", label);
        toggle.title = label;
      };
      toggle.setAttribute("aria-controls", tree.id);
      setExpanded();
      toggle.onclick = () => {
        if (expanded.has(workspace.id)) expanded.delete(workspace.id);
        else {
          expanded.add(workspace.id);
          if (!workspace.loaded) {
            select(workspace);
            return;
          }
        }
        setExpanded();
      };
      row.append(toggle, choose, indicator);
      section.append(row, tree);
      root.append(section);
    }
    if (state.listLoading)
      root.append(element("p", "file-row", "Loading workspaces…"));
    else if (state.listError) {
      const error = element("p", "file-row", state.listError);
      error.setAttribute("role", "alert");
      const action = button(
        "Retry loading workspaces",
        "refresh",
        "workspace-action",
      );
      action.onclick = retry;
      root.append(error, action);
    } else if (!state.workspaces.length)
      root.append(
        element(
          "p",
          "file-row",
          "No workspaces yet. Create one to get started.",
        ),
      );
    if (focused)
      [...root.querySelectorAll<HTMLElement>("[data-focus-key]")]
        .find((node) => node.dataset.focusKey === focused)
        ?.focus();
  }
  return {
    render,
    updateTask,
    expand(id: string) {
      expanded.add(id);
    },
  };
}
