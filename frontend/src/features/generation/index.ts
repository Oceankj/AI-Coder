import { button, element, icon } from "../../ui";
import { api, ApiError } from "../../api/client";
import { createInputDialog } from "../../components/input-dialog";
import type { ChatConfig } from "../../types";
import { createFloatingPanel } from "../../components/floating-panel";
import type { TaskStatus } from "./task-status";
import type { CanvasWorkspace } from "../workspaces/model";
import { createCallRecordsDialog } from "./records-dialog";

type ChatSession = Pick<CanvasWorkspace, "name" | "messages" | "draft" | "taskStatus" | "chatRunId"> & { id?: string };
export function createChatPanel(initial?: CanvasWorkspace) {
  const general: ChatSession = { name: "General chat", messages: [], draft: "" };
  let workspace: ChatSession = initial ?? general;
  let connection: ChatConfig | undefined;
  let connectionError = "";
  let connectionVersion = 0;
  const states = new WeakMap<ChatSession, { pending: boolean; outgoing: string; error: string }>();
  function sessionState(session = workspace) {
    let state = states.get(session);
    if (!state) { state = { pending: false, outgoing: "", error: "" }; states.set(session, state); }
    return state;
  }
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
  messages.setAttribute("aria-label", "Chat messages");
  messages.setAttribute("role", "region");
  const form = element("form", "composer");
  form.method = "post";
  form.setAttribute("aria-label", "Send a message to Gemini");
  const input = element("textarea");
  input.placeholder = "Describe what you want to build…";
  input.setAttribute("aria-label", "Message draft");
  input.name = "message";
  input.maxLength = 20000;
  input.rows = 3;
  const composerFooter = element("div", "composer-footer");
  const send = button("Send message", "arrow");
  send.type = "submit";
  send.classList.add("send-button");
  const chatStatus = element("span", "chat-connection-status");
  chatStatus.setAttribute("role", "status");
  const chatStatusText = element("span", "", "Checking Gemini…");
  const typingDots = element("span", "typing-dots");
  typingDots.setAttribute("aria-hidden", "true");
  typingDots.hidden = true;
  for (let index = 0; index < 3; index++) typingDots.append(element("span", "", "."));
  chatStatus.append(chatStatusText, typingDots);
  composerFooter.append(chatStatus, send);
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

  const keyButton = button("Gemini settings", undefined, "suggestion");
  keyButton.classList.add("chat-settings");
  const actions = element("div", "chat-actions");
  body.insertBefore(actions, messages);
  const newChat = button("New chat", undefined, "suggestion");
  newChat.classList.add("chat-settings");
  const records = createCallRecordsDialog();
  const recordsButton = button("Call records", undefined, "suggestion");
  recordsButton.onclick = () => records.open();
  actions.append(keyButton, newChat, recordsButton);
  newChat.onclick = () => {
    if (sessionState().pending) return;
    workspace.messages = [];
    workspace.draft = "";
    workspace.chatRunId = undefined;
    sessionState().error = "";
    input.value = "";
    renderMessages();
    input.focus();
  };
  const keyDialog = createInputDialog({
    id: "gemini-key", title: "Connect Gemini", closeLabel: "Close Gemini settings",
    label: "Gemini API key", placeholder: "Paste your Gemini API key", type: "password",
    description: "Create an API key in Google AI Studio, then paste it here.",
    hint: "Your key stays in this local backend's memory until it restarts. It is never saved to chat history or browser storage.",
    submitLabel: "Use API key", pendingLabel: "Adding key…",
    validate: value => /\s/.test(value) ? "Paste an API key without spaces." : undefined,
    submit: key => api.configureChat(key),
    onSuccess: config => {
      connectionVersion++;
      connection = config;
      connectionError = "";
      renderMessages();
      live.textContent = "API key added. Send a message to start chatting.";
      input.focus();
    },
  });
  const studio = element("a", "api-key-link", "Get an API key in Google AI Studio");
  studio.href = "https://aistudio.google.com/apikey";
  studio.target = "_blank";
  studio.rel = "noopener noreferrer";
  keyDialog.dialog.querySelector("form")!.insertBefore(studio, keyDialog.dialog.querySelector("label"));
  keyButton.onclick = () => keyDialog.open();

  function updateComposer() {
    const state = sessionState();
    input.disabled = state.pending;
    newChat.disabled = state.pending || !workspace.messages.length;
    send.disabled = !input.value.trim() || state.pending || !connection?.configured;
    form.setAttribute("aria-busy", String(state.pending));
    chatStatusText.textContent = state.pending ? "Gemini is replying" : connection?.configured ? (workspace.id ? "Gemini · Coordinator" : "Gemini · General chat") : "Add an API key to chat";
    typingDots.hidden = !state.pending;
    keyButton.textContent = connection?.configured ? "Gemini settings" : "Add Gemini API key";
    keyButton.setAttribute("aria-label", keyButton.textContent);
    keyButton.title = keyButton.textContent;
  }
  function appendMessage(role: "user" | "assistant", text: string) {
    const entry = element("div", `chat-message ${role === "user" ? "draft-message" : "assistant-message"}`);
    entry.append(element("span", "message-author", role === "user" ? "You" : "AI Coder"), element("p", "", text));
    messages.append(entry);
  }
  function renderMessages() {
    messages.replaceChildren();
    if (!connection?.configured) {
      const intro = element("div", "chat-intro");
      const mark = element("div", "agent-mark");
      mark.append(icon("spark"));
      intro.append(mark, element("h2", "", "Let’s connect Gemini."));
      intro.append(element("p", "", "Hi! Add your Gemini API key to start chatting with me. You can get one from Google AI Studio."));
      const add = button("Add API key", "plus", "suggestion");
      add.onclick = () => keyDialog.open();
      intro.append(add);
      messages.append(intro);
    } else if (!workspace.messages.length) {
      const intro = element("div", "chat-intro");
      intro.append(element("h2", "", "Let’s build something together."), element("p", "", "Ask a question, explore an idea, or plan your project. I can help you think and write code."));
      const suggestion = button("Help me plan this project", "plus", "suggestion");
      suggestion.onclick = () => {
        input.value = "Help me plan the features and implementation steps for this project.";
        workspace.draft = input.value;
        updateComposer();
        input.focus();
      };
      intro.append(suggestion);
      messages.append(intro);
    }
    for (const message of workspace.messages) appendMessage(message.role, message.content);
    renderRunReport();
    const state = sessionState();
    if (state.pending) appendMessage("user", state.outgoing);
    if (state.error || connectionError) {
      const error = element("p", "chat-error", state.error || connectionError);
      error.setAttribute("role", "alert");
      messages.append(error);
      if (connectionError) {
        const retry = button("Retry Gemini connection", "refresh", "suggestion");
        retry.onclick = () => { void loadConnection(); };
        messages.append(retry);
      }
    }
    updateComposer();
    messages.scrollTop = messages.scrollHeight;
  }
  function renderRunReport() {
    const status = workspace.taskStatus;
    if (workspace.chatRunId && status?.monitoredRunId === workspace.chatRunId &&
        ["completed", "blocked", "failed"].includes(status.state)) {
      appendMessage("assistant", `Run ${workspace.chatRunId}: ${status.report || status.text}`);
    }
  }
  async function loadConnection() {
    const version = ++connectionVersion;
    try {
      const config = await api.chatConfig();
      if (version !== connectionVersion) return;
      connection = config;
      connectionError = "";
    } catch (error) {
      if (version !== connectionVersion) return;
      connectionError = error instanceof Error ? error.message : "Could not reach the chat service.";
    }
    renderMessages();
  }
  function updateTask(status: TaskStatus) {
    if (workspace.chatRunId && (task.dataset.state !== status.state || task.title !== status.text)) renderMessages();
    taskText.textContent = status.text;
    task.title = status.text;
    task.dataset.state = status.state;
    panel.dataset.taskState = status.state;
  }
  function selectWorkspace(next: ChatSession) {
    workspace = next;
    project.textContent = workspace.name;
    project.title = workspace.name;
    updateTask(
      workspace.taskStatus ?? { text: "Chat ready", state: "idle" },
    );
    input.value = workspace.draft;
    updateComposer();
    renderMessages();
  }
  input.addEventListener("input", () => {
    workspace.draft = input.value;
    updateComposer();
  });
  let composing = false;
  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => { composing = false; });
  input.addEventListener("blur", () => { composing = false; });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    // Leave IME confirmation untouched. Safari can end composition before this
    // keydown and report isComposing=false, but still identifies it as key 229.
    if (composing || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!event.repeat && !send.disabled) form.requestSubmit(send);
  });
  form.onsubmit = async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    const target = workspace, state = sessionState(target);
    if (!text || state.pending) return;
    if (!connection?.configured) { keyDialog.open(); return; }
    state.pending = true;
    state.error = "";
    state.outgoing = text;
    target.draft = text;
    renderMessages();
    try {
      const reply = await api.chat([...target.messages.slice(-50), { role: "user", content: text }], undefined,
        { workspaceId: target.id, runId: target.chatRunId });
      if (reply.runId) target.chatRunId = reply.runId;
      target.messages.push({ role: "user", content: text }, reply.message);
      target.draft = "";
      if (workspace === target) {
        input.value = "";
        live.textContent = reply.message.content;
      }
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Could not send your message. Please try again.";
      if (error instanceof ApiError && ["GEMINI_KEY_REQUIRED", "GEMINI_KEY_INVALID"].includes(error.code)) {
        connectionVersion++;
        connection = { configured: false, model: connection?.model ?? "" };
      }
    } finally {
      state.pending = false;
      state.outgoing = "";
      if (workspace === target) {
        renderMessages();
        if (!collapsed) input.focus();
      } else if (!connection?.configured) {
        renderMessages();
      }
    }
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
  selectWorkspace(initial ?? general);
  void loadConnection();
  return { selectWorkspace, updateTask };
}
