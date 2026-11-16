import { button, element, icon } from "../ui";
export function createDialog(options: {
  id: string;
  title: string;
  closeLabel: string;
  className: string;
  icon?: string;
  lightDismiss?: boolean;
}) {
  const dialog = element("dialog", options.className);
  const header = element("header", "dialog-header");
  const title = element("h2", "", options.title);
  title.id = options.id;
  dialog.setAttribute("aria-labelledby", title.id);
  const close = button(options.closeLabel, "close");
  close.onclick = () => dialog.close();
  if (options.icon) header.append(icon(options.icon));
  header.append(title, close);
  dialog.append(header);
  if (options.lightDismiss) {
    dialog.setAttribute("closedby", "any");
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      const outside = (event: PointerEvent) => {
        const r = dialog.getBoundingClientRect();
        return (
          event.clientX < r.left ||
          event.clientX > r.right ||
          event.clientY < r.top ||
          event.clientY > r.bottom
        );
      };
      let downOutside = false;
      dialog.addEventListener("pointerdown", (event) => {
        downOutside = outside(event);
      });
      dialog.addEventListener("pointerup", (event) => {
        if (downOutside && outside(event)) dialog.close();
        downOutside = false;
      });
      dialog.addEventListener("pointercancel", () => {
        downOutside = false;
      });
    }
  }
  document.body.append(dialog);
  return { dialog, header, title, close };
}
