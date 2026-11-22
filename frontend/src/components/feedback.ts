// Author: Ching Kao
// Student ID: 85768427
import { button, element } from "../ui";
export function stateView(
  message: string,
  options: { error?: boolean; retry?: () => void } = {},
) {
  const view = element("div", "preview-empty");
  view.setAttribute("role", options.error ? "alert" : "status");
  view.append(element("p", "", message));
  if (options.retry) {
    const retry = button("Retry", "refresh", "primary-button");
    retry.onclick = options.retry;
    view.append(retry);
  }
  return view;
}
export function createNotice() {
  const view = element("div", "notice");
  view.setAttribute("role", "status");
  document.body.append(view);
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (message: string) => {
    view.textContent = message;
    clearTimeout(timer);
    timer = setTimeout(() => {
      view.textContent = "";
    }, 6000);
  };
}
