// Author: Ching Kao
// Student ID: 85768427
import { button, element } from "../ui";
import { createDialog } from "./dialog";
/** Shared accessible single-field form. A submitted mutation survives dismissal. */
export function createInputDialog<T>(options: {
  id: string;
  title: string;
  closeLabel: string;
  label: string;
  placeholder: string;
  submitLabel: string;
  type?: "text" | "url" | "password";
  description?: string;
  hint?: string;
  pendingLabel?: string;
  validate?: (value: string) => string | undefined;
  submit: (value: string) => T | Promise<T>;
  onSuccess: (result: T) => void;
  announce?: (message: string) => void;
  className?: string;
}) {
  const { dialog, header } = createDialog({
    id: `${options.id}-title`,
    title: options.title,
    closeLabel: options.closeLabel,
    className: `form-dialog ${options.className ?? ""}`,
  });
  const form = element("form");
  form.method = "post";
  form.setAttribute("aria-labelledby", `${options.id}-title`);
  form.append(header);
  if (options.description) form.append(element("p", "", options.description));
  const label = element("label", "", options.label);
  label.htmlFor = options.id;
  const input = element("input");
  input.id = options.id;
  input.name = options.id;
  input.type = options.type ?? "text";
  input.placeholder = options.placeholder;
  input.required = true;
  if (options.type === "password") {
    input.autocomplete = "new-password";
    input.spellcheck = false;
    input.autocapitalize = "none";
    input.maxLength = 512;
    dialog.addEventListener("close", () => { input.value = ""; });
  }
  input.autofocus = true;
  const error = element("p", "form-error");
  error.id = `${options.id}-error`;
  error.setAttribute("role", "alert");
  input.setAttribute("aria-describedby", error.id);
  const status = element("p", "field-hint");
  status.setAttribute("role", "status");
  const submit = button(options.submitLabel, undefined, "primary-button");
  submit.type = "submit";
  form.append(label, input);
  if (options.hint) form.append(element("p", "field-hint", options.hint));
  form.append(error, status, submit);
  dialog.append(form);
  let pending = false;
  input.oninput = () => {
    input.setCustomValidity("");
    input.removeAttribute("aria-invalid");
    error.textContent = "";
  };
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (pending) return;
    const value = input.value.trim();
    const invalid = !value ? "Enter a value." : options.validate?.(value);
    if (invalid) {
      error.textContent = invalid;
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    pending = true;
    input.disabled = true;
    submit.disabled = true;
    form.setAttribute("aria-busy", "true");
    status.textContent = options.pendingLabel ?? "";
    submit.textContent = options.pendingLabel ?? options.submitLabel;
    error.textContent = "";
    let result: T;
    try {
      result = await options.submit(value);
    } catch (cause) {
      const message =
        cause instanceof Error
          ? cause.message
          : "Something went wrong. Please try again.";
      error.textContent = message;
      if (!dialog.open) options.announce?.(message);
      return;
    } finally {
      pending = false;
      input.disabled = false;
      submit.disabled = false;
      form.removeAttribute("aria-busy");
      status.textContent = "";
      submit.textContent = options.submitLabel;
    }
    dialog.close();
    form.reset();
    options.onSuccess(result);
  };
  return {
    dialog,
    open(value = "") {
      if (!pending) {
        form.reset();
        input.value = value;
        input.removeAttribute("aria-invalid");
        input.setCustomValidity("");
        error.textContent = "";
      }
      dialog.showModal();
    },
  };
}
