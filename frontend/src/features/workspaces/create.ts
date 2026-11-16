import { api } from "../../api/client";
import { createInputDialog } from "../../components/input-dialog";
import type { WorkspaceSummary } from "../../types";
export function createWorkspaceDialog(
  onCreated: (workspace: WorkspaceSummary) => void,
  announce: (message: string) => void,
) {
  const form = createInputDialog({
    id: "workspace-name",
    title: "Create workspace",
    closeLabel: "Close create workspace",
    label: "Workspace name",
    placeholder: "My next project",
    submitLabel: "Create workspace",
    pendingLabel: "Creating…",
    submit: (name) => api.createWorkspace(name),
    onSuccess: onCreated,
    announce,
  });
  return () => form.open();
}
