import { button, element, icon } from "../../ui";
import type { CanvasWorkspace } from "../workspaces/model";

export function createChatPanel(initial: CanvasWorkspace) {
  let workspace = initial;
  let collapsed = false;
  let width = 358,
    height = 468;
  const homeTop = () =>
    (document.querySelector(".preview-toolbar")?.getBoundingClientRect()
      .bottom ?? 134) + 16;
  let left = Math.max(8, window.innerWidth - width - 24),
    top = homeTop();
  const panel = element("section", "chat-panel");
  panel.setAttribute("aria-label", "Agent conversation panel");
  const header = element("header", "chat-header");
  const handle = button("Move panel (use arrow keys)", "grip");
  handle.classList.add("drag-handle");
  const heading = element("div", "chat-heading");
  heading.append(icon("spark"), element("strong", "", "Agent"));
  const badge = element("span", "draft-badge", "Draft mode");
  const collapse = button("Collapse conversation panel", "minus");
  collapse.setAttribute("aria-expanded", "true");
  header.append(handle, heading, badge, collapse);
  const body = element("div", "chat-body");
  body.id = "chat-body";
  collapse.setAttribute("aria-controls", body.id);
  const context = element("div", "chat-context");
  const messages = element("div", "chat-messages");
  messages.setAttribute("aria-label", "Draft messages");
  const form = element("form", "composer");
  const input = element("textarea");
  input.placeholder = "Describe what you want to build…";
  input.setAttribute("aria-label", "Message draft");
  input.rows = 3;
  const composerFooter = element("div", "composer-footer");
  const send = button("Save draft", "arrow");
  send.type = "submit";
  send.classList.add("send-button");
  composerFooter.append(element("span", "", "Saved in this tab only"), send);
  form.append(input, composerFooter);
  const controls = element("div", "panel-controls");
  const placement = element("select");
  placement.setAttribute("aria-label", "Panel position");
  for (const [value, text] of [
    ["", "Move panel…"],
    ["tl", "Top left"],
    ["tr", "Top right"],
    ["bl", "Bottom left"],
    ["br", "Bottom right"],
  ]) {
    const option = element("option", "", text);
    option.value = value;
    placement.append(option);
  }
  const size = element("select");
  size.setAttribute("aria-label", "Panel size");
  for (const [value, text] of [
    ["normal", "Standard size"],
    ["large", "Large size"],
  ]) {
    const option = element("option", "", text);
    option.value = value;
    size.append(option);
  }
  const resize = button("Resize panel (use arrow keys)", "resize");
  resize.classList.add("resize-handle");
  controls.append(placement, size, resize);
  body.append(context, messages, form, controls);
  panel.append(header, body);
  const live = element("div", "sr-only");
  live.setAttribute("aria-live", "polite");
  document.body.append(panel, live);

  function layout() {
    const maxWidth = Math.max(1, window.innerWidth - 16),
      maxHeight = Math.max(1, window.innerHeight - 16);
    width = Math.min(Math.max(Math.min(300, maxWidth), width), maxWidth);
    height = Math.min(Math.max(Math.min(340, maxHeight), height), maxHeight);
    const visibleWidth = collapsed ? Math.min(276, maxWidth) : width;
    left = Math.max(8, Math.min(left, window.innerWidth - visibleWidth - 8));
    top = Math.max(
      8,
      Math.min(top, window.innerHeight - (collapsed ? 54 : height) - 8),
    );
    Object.assign(panel.style, {
      left: `${left}px`,
      top: `${top}px`,
      width: `${visibleWidth}px`,
      height: `${collapsed ? 54 : height}px`,
    });
  }
  function renderMessages() {
    messages.replaceChildren();
    if (!workspace.messages.length) {
      const intro = element("div", "chat-intro");
      const mark = element("div", "agent-mark");
      mark.append(icon("spark"));
      intro.append(
        mark,
        element("h2", "", "Let’s build something together."),
        element(
          "p",
          "",
          "Capture your ideas, questions, or next steps.\nConnect an agent to start collaborating.",
        ),
      );
      const suggestion = button(
        "Help me plan this project",
        "plus",
        "suggestion",
      );
      suggestion.onclick = () => {
        input.value =
          "Help me plan the features and implementation steps for this project.";
        workspace.draft = input.value;
        send.disabled = false;
        input.focus();
      };
      intro.append(suggestion);
      messages.append(intro);
    }
    for (const text of workspace.messages) {
      const entry = element("div", "draft-message");
      entry.append(
        element("span", "", "You · Not sent"),
        element("p", "", text),
      );
      messages.append(entry);
    }
    messages.scrollTop = messages.scrollHeight;
  }
  function selectWorkspace(next: CanvasWorkspace) {
    workspace = next;
    context.replaceChildren(
      icon("folder"),
      element("span", "", workspace.name),
    );
    input.value = workspace.draft;
    send.disabled = !input.value.trim();
    renderMessages();
  }
  input.addEventListener("input", () => {
    workspace.draft = input.value;
    send.disabled = !input.value.trim();
  });
  form.onsubmit = (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    workspace.messages.push(text);
    workspace.draft = "";
    input.value = "";
    send.disabled = true;
    renderMessages();
    live.textContent =
      "Draft saved in this tab. It has not been sent to an agent.";
    input.focus();
  };
  collapse.onclick = () => {
    collapsed = !collapsed;
    body.hidden = collapsed;
    panel.classList.toggle("collapsed", collapsed);
    collapse.replaceChildren(icon(collapsed ? "chat" : "minus"));
    const label = collapsed
      ? "Expand conversation panel"
      : "Collapse conversation panel";
    collapse.setAttribute("aria-label", label);
    collapse.title = label;
    collapse.setAttribute("aria-expanded", String(!collapsed));
    layout();
  };
  function pointerControl(control: HTMLButtonElement, resizing: boolean) {
    let startX = 0,
      startY = 0,
      startLeft = 0,
      startTop = 0,
      startWidth = 0,
      startHeight = 0;
    control.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary) return;
      startX = event.clientX;
      startY = event.clientY;
      startLeft = left;
      startTop = top;
      startWidth = width;
      startHeight = height;
      control.setPointerCapture(event.pointerId);
      document.body.classList.add("moving-panel");
      control.classList.add("dragging");
    });
    control.addEventListener("pointermove", (event) => {
      if (!control.hasPointerCapture(event.pointerId)) return;
      if (resizing) {
        width = Math.min(
          startWidth + event.clientX - startX,
          window.innerWidth - left - 8,
        );
        height = Math.min(
          startHeight + event.clientY - startY,
          window.innerHeight - top - 8,
        );
      } else {
        left = startLeft + event.clientX - startX;
        top = startTop + event.clientY - startY;
      }
      layout();
    });
    const finish = () => {
      document.body.classList.remove("moving-panel");
      control.classList.remove("dragging");
      live.textContent = resizing ? "Panel resized." : "Panel moved.";
    };
    control.addEventListener("pointerup", (event) => {
      if (control.hasPointerCapture(event.pointerId))
        control.releasePointerCapture(event.pointerId);
    });
    control.addEventListener("pointercancel", finish);
    control.addEventListener("lostpointercapture", finish);
    control.addEventListener("keydown", (event) => {
      const moves: Record<string, [number, number]> = {
        ArrowLeft: [-16, 0],
        ArrowRight: [16, 0],
        ArrowUp: [0, -16],
        ArrowDown: [0, 16],
      };
      const move = moves[event.key];
      if (!move) return;
      event.preventDefault();
      if (resizing) {
        width += move[0];
        height += move[1];
      } else {
        left += move[0];
        top += move[1];
      }
      layout();
      finish();
    });
  }
  pointerControl(handle, false);
  pointerControl(resize, true);
  placement.onchange = () => {
    if (!placement.value) return;
    left = placement.value.endsWith("l") ? 16 : window.innerWidth - width - 16;
    top = placement.value.startsWith("t")
      ? homeTop()
      : window.innerHeight - height - 16;
    layout();
    live.textContent = `Panel moved to ${placement.selectedOptions[0].textContent}.`;
    placement.value = "";
  };
  size.onchange = () => {
    width = size.value === "large" ? 460 : 358;
    height = size.value === "large" ? 580 : 468;
    layout();
  };
  window.addEventListener("resize", layout);
  selectWorkspace(initial);
  layout();
  return { selectWorkspace };
}
