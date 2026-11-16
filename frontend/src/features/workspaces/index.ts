import { button, element, icon } from "../../ui";
import type { CanvasWorkspace, WorkspaceFile } from "./model";
interface Directory {
  folders: Map<string, Directory>;
  files: WorkspaceFile[];
}
export function workspaceTree(
  workspace: CanvasWorkspace,
  openFile: (file: WorkspaceFile) => void,
): HTMLUListElement {
  const root: Directory = { folders: new Map(), files: [] };
  for (const file of workspace.files) {
    const parts = file.path.split("/");
    let directory = root;
    for (const name of parts.slice(0, -1)) {
      if (!directory.folders.has(name))
        directory.folders.set(name, { folders: new Map(), files: [] });
      directory = directory.folders.get(name)!;
    }
    directory.files.push(file);
  }
  function render(directory: Directory): HTMLUListElement {
    const list = element("ul", "file-tree");
    for (const [name, child] of [...directory.folders].sort(([a], [b]) =>
      a.localeCompare(b),
    )) {
      const item = element("li");
      const disclosure = element("details");
      disclosure.open = true;
      const summary = element("summary", "file-row folder-row");
      summary.append(
        icon("chevron"),
        icon("folder"),
        element("span", "", name),
      );
      disclosure.append(summary, render(child));
      item.append(disclosure);
      list.append(item);
    }
    for (const file of directory.files.sort((a, b) =>
      a.path.localeCompare(b.path),
    )) {
      const item = element("li");
      const name = file.path.split("/").at(-1)!;
      const row = button(
        name,
        /\.(html|css|js|ts|json)$/.test(name) ? "code" : "file",
        "file-row",
      );
      row.title = file.path;
      row.addEventListener("click", () => openFile(file));
      item.append(row);
      list.append(item);
    }
    return list;
  }
  return render(root);
}
