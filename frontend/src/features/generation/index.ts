import { button, element, icon } from "../../ui";
import { createFloatingPanel } from "../../components/floating-panel";
import type { TaskStatus } from "./task-status";
import type { CanvasWorkspace } from "../workspaces/model";

export function createChatPanel(initial: CanvasWorkspace) {
  let workspace = initial;
  let collapsed = false;
  const panel = element("section", "chat-panel");
  panel.setAttribute("aria-label", "Agent conversation panel");
  const header = element("header", "chat-header");
  const handle = button("Move panel (use arrow keys)", "grip");
  handle.classList.add("drag-handle");
  const heading = element("div", "chat-heading");
  const summary = element("div", "chat-summary");
  const titleRow = element("div", "chat-title-row");
  const project = element("span", "chat-project");
  project.setAttribute("aria-label", "Current project");
  titleRow.append(element("strong", "", "AI Coder"), project);
  const task = element("div", "chat-task");
  task.setAttribute("role", "status");
  const taskText = element("span");
  task.append(taskText);
  summary.append(titleRow, task);
  const glowToggle = button("Pause glow animation", "spark");
  glowToggle.classList.add("chat-glow-toggle");
  let glowPaused = false;
  const motionPreference = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  );
  function updateGlow() {
    panel.classList.toggle("glow-paused", glowPaused);
    glowToggle.disabled = motionPreference.matches;
    const label = motionPreference.matches
      ? "Glow disabled by reduced motion"
      : glowPaused
        ? "Resume glow animation"
        : "Pause glow animation";
    glowToggle.setAttribute("aria-label", label);
    glowToggle.title = label;
  }
  glowToggle.onclick = () => {
    glowPaused = !glowPaused;
    updateGlow();
  };
  motionPreference.addEventListener("change", updateGlow);
  updateGlow();
  heading.append(glowToggle, summary);
  const collapse = button("Collapse conversation panel", "minus");
  collapse.setAttribute("aria-expanded", "true");
  header.append(handle, heading, collapse);
  collapse.classList.add("chat-collapse");
  const body = element("div", "chat-body");
  body.id = "chat-body";
  collapse.setAttribute("aria-controls", body.id);
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
  const resize = button("Resize panel (use arrow keys)", "resize");
  resize.classList.add("resize-handle");
  controls.append(resize);
  body.append(messages, form, controls);
  panel.append(header, body);
  const live = element("div", "sr-only");
  live.setAttribute("aria-live", "polite");
  document.body.append(panel, live);
  const floating = createFloatingPanel({
    panel,
    header,
    handle,
    resize,
    top: () =>
      (document.querySelector(".preview-toolbar")?.getBoundingClientRect()
        .bottom ?? 134) + 16,
    announce: (message) => {
      live.textContent = message;
    },
  });

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
  function updateTask(status: TaskStatus) {
    taskText.textContent = status.text;
    task.title = status.text;
    task.dataset.state = status.state;
    panel.dataset.taskState = status.state;
  }
  function selectWorkspace(next: CanvasWorkspace) {
    workspace = next;
    project.textContent = workspace.name;
    project.title = workspace.name;
    updateTask(
      workspace.taskStatus ?? { text: "Loading task…", state: "loading" },
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
    floating.setCollapsed(collapsed);
  };
  selectWorkspace(initial);
  return { selectWorkspace, updateTask };
}
