import { api } from "../../api/client";
import { button, element } from "../../ui";
import type { WorkspaceSummary } from "../../types";

export function createWorkspaceDialog(
  onCreated: (workspace: WorkspaceSummary) => void,
  announce: (message: string) => void,
) {
  const dialog = element("dialog", "form-dialog");
  dialog.setAttribute("aria-labelledby", "create-workspace-title");
  const form = element("form");
  form.method = "post";
  form.setAttribute("aria-labelledby", "create-workspace-title");
  const header = element("div", "dialog-header");
  const title = element("h2", "", "Create workspace");
  title.id = "create-workspace-title";
  const close = button("Close create workspace", "close");
  close.onclick = () => dialog.close();
  header.append(title, close);
  const label = element("label", "", "Workspace name");
  label.htmlFor = "workspace-name";
  const input = element("input");
  input.id = "workspace-name";
  input.name = "name";
  input.required = true;
  input.autofocus = true;
  input.placeholder = "My next project";
  const error = element("p", "form-error");
  error.id = "create-workspace-error";
  error.setAttribute("role", "alert");
  input.setAttribute("aria-describedby", error.id);
  const status = element("p", "field-hint");
  status.setAttribute("role", "status");
  const submit = button("Create workspace", undefined, "primary-button");
  submit.type = "submit";
  form.append(header, label, input, error, status, submit);
  dialog.append(form);
  document.body.append(dialog);
  let pending = false;
  input.addEventListener("input", () => {
    input.setCustomValidity("");
    input.removeAttribute("aria-invalid");
    error.textContent = "";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending) return;
    const name = input.value.trim();
    if (!name) {
      input.setCustomValidity("Enter a workspace name.");
      input.setAttribute("aria-invalid", "true");
      input.reportValidity();
      return;
    }
    pending = true;
    input.disabled = true;
    submit.disabled = true;
    submit.textContent = "Creating…";
    status.textContent = "Creating your workspace…";
    error.textContent = "";
    form.setAttribute("aria-busy", "true");
    // Closing the dialog does not abort a POST that may already have committed.
    let created: WorkspaceSummary;
    try {
      created = await api.createWorkspace(name);
    } catch (cause) {
      const message =
        cause instanceof Error
          ? cause.message
          : "Could not create workspace. Please try again.";
      error.textContent = message;
      if (!dialog.open) announce(message);
      return;
    } finally {
      pending = false;
      input.disabled = false;
      submit.disabled = false;
      submit.textContent = "Create workspace";
      status.textContent = "";
      form.removeAttribute("aria-busy");
    }
    dialog.close();
    form.reset();
    onCreated(created);
  });
  return () => {
    if (!pending) {
      form.reset();
      input.setCustomValidity("");
      input.removeAttribute("aria-invalid");
      error.textContent = "";
    }
    dialog.showModal();
  };
}
