// Author: Ching Kao
// Student ID: 85768427
import { button, element, icon } from "../../ui";
import { api, ApiError } from "../../api/client";
import { createInputDialog } from "../../components/input-dialog";
import type { ChatConfig, ChatProvider, GroqModel } from "../../types";
import { createFloatingPanel } from "../../components/floating-panel";
import { describeTask, type TaskStatus } from "./task-status";
import type { CanvasWorkspace } from "../workspaces/model";
import { createCallRecordsDialog } from "./records-dialog";
import { readChatHistory, readChatProvider, readGroqModel, saveChatHistory, saveChatProvider, saveGroqModel, type TaskNotice } from "./history";

const providerNames: Record<ChatProvider, string> = {
  gemini: "Gemini",
  groq: "Groq",
  codex: "Codex CLI",
};

const taskTitles = { queued: "Queued", blocked: "Blocked", completed: "Completed", failed: "Failed", stopped: "Stopped" } as const;

function appendProse(parent: HTMLElement, text: string) {
  for (const block of text.trim().split(/\r?\n(?:[ \t]*\r?\n)+/)) {
    if (!block) continue;
    const heading = block.match(/^#{1,6}[ \t]+([^\r\n]+)(?:\r?\n([\s\S]*))?$/);
    if (heading) parent.append(element("h3", "", heading[1]));
    const body = heading ? heading[2] : block;
    if (!body) continue;
    const paragraph = element("p");
    let start = 0;
    for (const emphasis of body.matchAll(/\*\*([^*\r\n]+)\*\*/g)) {
      paragraph.append(body.slice(start, emphasis.index), element("strong", "", emphasis[1]));
      start = emphasis.index + emphasis[0].length;
    }
    paragraph.append(body.slice(start));
    parent.append(paragraph);
  }
}

type ChatSession = Pick<CanvasWorkspace, "name" | "messages" | "notices" | "draft" | "taskStatus" | "chatRunId" | "chatCleared"> & { id?: string };
type ChatActivity = {
  pending: boolean;
  outgoing: string;
  error: string;
  reply?: AbortController;
  stopMessage?: string;
  stopping?: boolean;
  finishedRunId?: string;
};
export function createChatPanel(initial?: CanvasWorkspace) {
  const general: ChatSession = { name: "General chat", messages: [], notices: [], draft: "" };
  let workspace: ChatSession = initial ?? general;
  const restored = new WeakSet<ChatSession>();
  const restoring = new WeakSet<ChatSession>();
  const draftTimers = new WeakMap<ChatSession, number>();
  async function restore(session: ChatSession) {
    restoring.add(session);
    try {
      const saved = await readChatHistory(session.id);
      if (saved) {
        session.messages = saved.messages;
        session.notices = saved.notices;
        session.draft = saved.draft;
        session.chatRunId = saved.chatRunId;
        session.chatCleared = saved.cleared;
      }
    } catch {
      sessionState(session).error = "Could not load chat history from this browser.";
    } finally {
      restoring.delete(session);
      restored.add(session);
      if (workspace === session) {
        input.value = session.draft;
        if (session.taskStatus) updateTask(session.taskStatus);
        renderMessages();
      }
    }
  }
  function persist(session: ChatSession): Promise<void> {
    return saveChatHistory(session.id, {
      messages: session.messages, notices: session.notices, draft: session.draft,
      chatRunId: session.chatRunId, cleared: session.chatCleared,
    }).catch(() => {
      sessionState(session).error = "Could not save chat history in this browser.";
      if (workspace === session) renderMessages();
    });
  }
  function saveDraftSoon(session: ChatSession) {
    window.clearTimeout(draftTimers.get(session));
    draftTimers.set(session, window.setTimeout(() => { void persist(session); }, 300));
  }
  let selectedProvider: ChatProvider = "gemini";
  let connection: ChatConfig | undefined;
  let connectionError = "";
  let connectionVersion = 0;
  const states = new WeakMap<ChatSession, ChatActivity>();
  const openInstructions = new WeakSet<TaskNotice>();
  let renderedSession: ChatSession | undefined;
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
  summary.append(titleRow);
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
  const transcript = element("div");
  const replyStatus = element("div");
  replyStatus.setAttribute("role", "status");
  const waitingReply = element("p", "chat-waiting-reply", "Responding…");
  const stopFeedback = element("p", "chat-stop-feedback");
  const typingDots = element("span", "typing-dots");
  typingDots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index++) typingDots.append(element("span"));
  waitingReply.append(typingDots);
  messages.append(transcript, replyStatus);
  const form = element("form", "composer");
  form.method = "post";
  form.setAttribute("aria-label", "Send a chat message");
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
  const stop = button("Stop response", "stop", "stop-button");
  const stopLabel = stop.querySelector("span")!;
  stop.hidden = true;
  const composerActions = element("div", "composer-actions");
  composerActions.append(stop, send);
  const chatStatus = element("span", "chat-connection-status");
  chatStatus.setAttribute("role", "status");
  const chatStatusText = element("span", "", "Checking connection…");
  chatStatus.append(chatStatusText);
  composerFooter.append(chatStatus, composerActions);
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

  const keyButton = button("API key settings", undefined, "suggestion");
  keyButton.classList.add("chat-settings");
  const actions = element("div", "chat-actions");
  body.insertBefore(actions, messages);
  const newChat = button("New chat", undefined, "suggestion");
  newChat.classList.add("chat-settings");
  const records = createCallRecordsDialog();
  const recordsButton = button("Call records", undefined, "suggestion");
  recordsButton.onclick = () => records.open();
  const providerLabel = element("label", "chat-provider suggestion", "Provider");
  const providerSelect = element("select");
  for (const [provider, name] of Object.entries(providerNames)) {
    providerSelect.append(new Option(name, provider));
  }
  providerLabel.append(providerSelect);
  actions.append(providerLabel, keyButton, newChat, recordsButton);
  providerSelect.onchange = () => {
    selectedProvider = providerSelect.value as ChatProvider;
    connection = undefined;
    connectionError = "";
    sessionState().error = "";
    renderMessages();
    void saveChatProvider(selectedProvider).catch(() => {
      live.textContent = "Could not save the provider choice in this browser.";
    });
    void loadConnection();
  };
  newChat.onclick = async () => {
    if (sessionState().pending) return;
    const target = workspace;
    window.clearTimeout(draftTimers.get(target));
    target.messages = [];
    target.notices = [];
    target.draft = "";
    target.chatRunId = undefined;
    target.chatCleared = true;
    sessionState(target).error = "";
    sessionState(target).stopMessage = undefined;
    await persist(target);
    if (workspace === target) {
      input.value = "";
      renderMessages();
      input.focus();
    }
  };
  function providerName() {
    return providerNames[selectedProvider];
  }
  function createKeyDialog(provider: Exclude<ChatProvider, "codex">) {
    const name = providerNames[provider];
    const consoleName = provider === "groq" ? "Groq Console" : "Google AI Studio";
    const keyDialog = createInputDialog({
      id: `${provider}-key`, title: `Connect ${name}`, closeLabel: `Close ${name} settings`,
      label: `${name} API key`, placeholder: `Paste your ${name} API key`, type: "password",
      description: `Create an API key in ${consoleName}, then paste it here.`,
      hint: "Your key stays in this local backend's memory until it restarts. It is never saved to chat history or browser storage.",
      submitLabel: "Use API key", pendingLabel: "Adding key…",
      validate: value => /\s/.test(value) ? "Paste an API key without spaces." : undefined,
      submit: key => api.configureChat(key, provider),
      onSuccess: config => {
        if (selectedProvider !== provider) return;
        connectionVersion++;
        connection = config;
        connectionError = "";
        renderMessages();
        live.textContent = "API key added. Send a message to start chatting.";
        input.focus();
      },
    });
    const studio = element("a", "api-key-link", `Get an API key in ${consoleName}`);
    studio.href = provider === "groq" ? "https://console.groq.com/keys" : "https://aistudio.google.com/apikey";
    studio.target = "_blank";
    studio.rel = "noopener noreferrer";
    const keyForm = keyDialog.dialog.querySelector("form")!;
    const keyLabel = keyForm.querySelector("label")!;
    keyForm.insertBefore(studio, keyLabel);
    let modelSelect: HTMLSelectElement | undefined;
    if (provider === "groq") {
      const label = element("label", "", "Groq model");
      modelSelect = element("select");
      modelSelect.id = "groq-model";
      label.htmlFor = modelSelect.id;
      modelSelect.append(
        new Option("GPT-OSS 120B", "openai/gpt-oss-120b"),
        new Option("GPT-OSS 20B", "openai/gpt-oss-20b"),
      );
      const status = element("p", "field-hint");
      status.id = "groq-model-status";
      status.setAttribute("role", "status");
      modelSelect.setAttribute("aria-describedby", status.id);
      modelSelect.onchange = async () => {
        const chosen = modelSelect!.value as GroqModel;
        modelSelect!.disabled = true;
        status.textContent = "Saving model…";
        try {
          const config = await api.setGroqModel(chosen);
          if (selectedProvider === "groq") connection = config;
          await saveGroqModel(chosen);
          status.textContent = `${chosen} selected for new Groq calls.`;
          renderMessages();
        } catch (error) {
          modelSelect!.value = connection?.model ?? "openai/gpt-oss-120b";
          status.textContent = error instanceof Error ? error.message : "Could not save the model.";
        } finally {
          modelSelect!.disabled = false;
        }
      };
      keyForm.insertBefore(label, keyLabel);
      keyForm.insertBefore(modelSelect, keyLabel);
      keyForm.insertBefore(status, keyLabel);
    }
    return { ...keyDialog, provider, modelSelect };
  }
  let keyDialog: ReturnType<typeof createKeyDialog> | undefined;
  function openKeyDialog() {
    const provider = selectedProvider;
    if (!connection || provider === "codex") return;
    if (keyDialog?.provider !== provider) {
      keyDialog?.dialog.remove();
      keyDialog = createKeyDialog(provider);
    }
    keyDialog.open();
    if (keyDialog.modelSelect && connection?.model) keyDialog.modelSelect.value = connection.model;
  }
  keyButton.onclick = openKeyDialog;

  function activeRunId(session: ChatSession) {
    const task = session.taskStatus;
    if (!session.id || !task?.monitoredRunId || (task.state !== "queued" && task.state !== "running")) return;
    if (task.monitoredRunId !== sessionState(session).finishedRunId) return task.monitoredRunId;
  }
  function updateComposer() {
    const state = sessionState();
    input.disabled = state.pending || restoring.has(workspace);
    newChat.disabled = state.pending || restoring.has(workspace) || (!workspace.messages.length && !workspace.notices.length);
    send.disabled = !input.value.trim() || state.pending || state.stopping || restoring.has(workspace) || !connection?.configured;
    send.hidden = !!state.reply;
    stop.hidden = !(state.reply || state.stopping || activeRunId(workspace));
    stop.disabled = !!(state.stopping || state.reply?.signal.aborted);
    const stopText = stop.disabled ? "Stopping…" : state.reply ? "Stop response" : "Stop generation";
    stopLabel.textContent = stopText;
    stop.setAttribute("aria-label", stopText);
    stop.title = stopText;
    form.setAttribute("aria-busy", String(state.pending));
    const codex = selectedProvider === "codex";
    const connected = codex
      ? [providerName(), connection?.model, connection?.effort === "low" ? "Low reasoning" : ""].filter(Boolean).join(" · ")
      : `${providerName()} · ${workspace.id ? "Coordinator" : "General chat"}`;
    chatStatusText.textContent = connection?.configured
      ? connected
      : codex ? "Codex CLI login required" : "Add an API key to chat";
    providerSelect.disabled = state.pending;
    keyButton.hidden = codex;
    keyButton.disabled = !connection;
    keyButton.textContent = !connection ? "API key settings" : connection.configured ? `${providerName()} settings` : `Add ${providerName()} API key`;
    keyButton.setAttribute("aria-label", keyButton.textContent);
    keyButton.title = keyButton.textContent;
  }
  function appendMessage(role: "user" | "assistant", text: string) {
    const entry = element("div", `chat-message ${role === "user" ? "draft-message" : "assistant-message"}`);
    entry.append(element("span", "message-author", role === "user" ? "You" : "AI Coder"));
    if (role === "user") entry.append(element("p", "", text));
    else {
      const prose = element("div", "chat-prose");
      appendProse(prose, text);
      entry.append(prose);
    }
    transcript.append(entry);
  }
  function appendNotice(notice: TaskNotice) {
    if (notice.kind === "handoff") {
      const entry = element("div", "chat-message handoff-message");
      if (notice.taskId) entry.dataset.taskId = notice.taskId;
      const legacy = notice.featureTitle === undefined
        ? notice.text.match(/^([\s\S]*?)\n\nFeature: ([^\n]+)(?:\n([\s\S]*))?$/)
        : null;
      const title = notice.featureTitle ?? legacy?.[2];
      const description = notice.featureDescription ?? legacy?.[3];
      const instructions = legacy?.[1] ?? notice.text;
      const role = notice.role ?? "agent";
      entry.append(element("span", "message-author", `${role[0].toUpperCase()}${role.slice(1)}`));
      if (title) entry.append(element("h3", "handoff-title", title));
      const criteria = description?.split(/\r?\n/).map(line => line.trim()).filter(Boolean) ?? [];
      if (criteria.length > 1) {
        const list = element("ul", "handoff-criteria");
        for (const line of criteria) list.append(element("li", "", line));
        entry.append(list);
      } else if (criteria[0]) {
        entry.append(element("p", "handoff-criteria", criteria[0]));
      }
      if (instructions) {
        const details = element("details", "handoff-instructions");
        details.open = openInstructions.has(notice);
        details.ontoggle = () => {
          if (details.open) openInstructions.add(notice);
          else openInstructions.delete(notice);
        };
        details.append(element("summary", "", "Full instructions"), element("p", "", instructions));
        entry.append(details);
      }
      transcript.append(entry);
      return;
    }
    const entry = element("div", "chat-message task-message");
    entry.dataset.state = notice.state;
    if (notice.state === "running") {
      const progress = element("p", "task-progress");
      const suffix = " is working…";
      if (notice.text.endsWith(suffix)) progress.append(element("strong", "", notice.text.slice(0, -suffix.length)), suffix);
      else progress.textContent = notice.text;
      entry.append(progress);
    } else {
      const title = taskTitles[notice.state];
      const prefix = `${title} · `;
      const detail = notice.text.startsWith(prefix) ? notice.text.slice(prefix.length) : notice.text;
      entry.append(element("strong", "task-title", title));
      if (detail !== title && !(notice.state === "completed" && detail === "Run completed.")) {
        const prose = element("div", "task-detail chat-prose");
        appendProse(prose, detail);
        entry.append(prose);
      }
    }
    transcript.append(entry);
  }
  function renderMessages() {
    const state = sessionState();
    const scrollTop = messages.scrollTop;
    const followLatest = renderedSession !== workspace || messages.scrollHeight - messages.clientHeight - scrollTop < 24;
    const focusedSummary = renderedSession === workspace && document.activeElement?.matches(".handoff-instructions > summary")
      ? document.activeElement.closest<HTMLElement>(".handoff-message")?.dataset.taskId
      : undefined;
    renderedSession = workspace;
    transcript.replaceChildren();
    if (state.stopMessage && stopFeedback.textContent !== state.stopMessage) stopFeedback.textContent = state.stopMessage;
    const feedback = state.pending ? waitingReply : state.stopMessage ? stopFeedback : null;
    if (replyStatus.firstChild !== feedback) replyStatus.replaceChildren(...(feedback ? [feedback] : []));
    if (restoring.has(workspace)) {
      transcript.append(element("p", "chat-intro", "Loading conversation…"));
      updateComposer();
      return;
    }
    if (!connection) {
      if (!connectionError) transcript.append(element("p", "chat-intro", "Checking connection…"));
    } else if (!connection.configured) {
      const intro = element("div", "chat-intro");
      const mark = element("div", "agent-mark");
      mark.append(icon("spark"));
      intro.append(mark, element("h2", "", `Let’s connect ${providerName()}.`));
      if (selectedProvider === "codex") {
        intro.append(element("p", "", "Run codex login on the computer running AI Coder, then check the login again."));
        const checkLogin = button("Check Codex login", "refresh", "suggestion");
        checkLogin.onclick = () => { void loadConnection(); };
        intro.append(checkLogin);
      } else {
        intro.append(element("p", "", `Add your ${providerName()} API key to start chatting.`));
        const add = button("Add API key", "plus", "suggestion");
        add.onclick = openKeyDialog;
        intro.append(add);
      }
      transcript.append(intro);
    } else if (!workspace.messages.length && !workspace.notices.length && !state.pending) {
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
      transcript.append(intro);
    }
    for (let index = 0; index <= workspace.messages.length; index++) {
      if (index) {
        const message = workspace.messages[index - 1];
        appendMessage(message.role, message.content);
      }
      for (const notice of workspace.notices) {
        if (notice.afterMessageCount === index) appendNotice(notice);
      }
    }
    if (state.outgoing) appendMessage("user", state.outgoing);
    if (state.error || connectionError) {
      const error = element("p", "chat-error", state.error || connectionError);
      error.setAttribute("role", "alert");
      transcript.append(error);
      if (connectionError) {
        const retry = button("Retry chat connection", "refresh", "suggestion");
        retry.onclick = () => { void loadConnection(); };
        transcript.append(retry);
      }
    }
    updateComposer();
    messages.scrollTop = followLatest ? messages.scrollHeight : scrollTop;
    if (focusedSummary) {
      transcript.querySelector<HTMLElement>(`[data-task-id="${CSS.escape(focusedSummary)}"] summary`)?.focus({ preventScroll: true });
    }
  }
  async function loadConnection() {
    const version = ++connectionVersion;
    try {
      let config = await api.chatConfig(selectedProvider);
      if (version !== connectionVersion) return;
      if ((config.provider ?? "gemini") !== selectedProvider) throw new Error("This backend does not support the selected provider.");
      if (selectedProvider === "groq") {
        const savedModel = await readGroqModel();
        if (version !== connectionVersion) return;
        if (savedModel && config.model !== savedModel) config = await api.setGroqModel(savedModel);
        if (version !== connectionVersion) return;
      }
      connection = config;
      connectionError = "";
    } catch (error) {
      if (version !== connectionVersion) return;
      connectionError = error instanceof Error ? error.message : "Could not reach the chat service.";
    }
    renderMessages();
  }
  function updateTask(status: TaskStatus) {
    if (!workspace.id || !status.monitoredRunId || restoring.has(workspace)) return;
    updateComposer();
    // Existing workspaces may have a run from before chat history was saved.
    if (!workspace.chatRunId && !workspace.chatCleared && !sessionState().pending &&
        !workspace.messages.length && !workspace.notices.length) {
      workspace.chatRunId = status.monitoredRunId;
    }
    if (workspace.chatRunId !== status.monitoredRunId ||
        !["queued", "running", "blocked", "completed", "failed", "stopped"].includes(status.state)) return;
    const target = workspace;
    if (status.monitoredRunId === sessionState(target).finishedRunId &&
        (status.state === "queued" || status.state === "running")) return;
    let changed = false;
    for (const task of status.handoffs ?? []) {
      if (target.notices.some(notice => notice.kind === "handoff" &&
          notice.runId === status.monitoredRunId && notice.taskId === task.id)) continue;
      target.notices.push({
        kind: "handoff", taskId: task.id, role: task.role,
        runId: status.monitoredRunId, state: "running",
        text: task.instructions,
        featureTitle: task.featureTitle,
        featureDescription: task.featureDescription,
        afterMessageCount: target.messages.length,
      });
      changed = true;
    }
    const state = status.state as TaskNotice["state"];
    const text = status.report && ["blocked", "completed"].includes(state)
      ? `${state === "completed" ? "Completed" : "Blocked"} · ${status.report}`
      : status.text;
    const last = [...target.notices].reverse().find(
      notice => notice.kind !== "handoff" && notice.runId === status.monitoredRunId,
    );
    if (last?.state !== state || last.text !== text) {
      target.notices.push({ runId: status.monitoredRunId, state, text, afterMessageCount: target.messages.length });
      changed = true;
    }
    if (!changed) return;
    void persist(target).then(() => {
      if (workspace === target) {
        renderMessages();
        live.textContent = text;
      }
    });
  }
  function selectWorkspace(next: ChatSession) {
    workspace = next;
    project.textContent = workspace.name;
    project.title = workspace.name;
    input.value = sessionState().pending ? "" : workspace.draft;
    if (!restored.has(workspace)) {
      void restore(workspace);
      renderMessages();
      return;
    }
    if (workspace.taskStatus) updateTask(workspace.taskStatus);
    renderMessages();
  }
  input.addEventListener("input", () => {
    workspace.draft = input.value;
    saveDraftSoon(workspace);
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
  stop.onclick = async () => {
    const target = workspace, state = sessionState(target);
    if (state.reply) {
      state.reply.abort();
      updateComposer();
      return;
    }
    const runId = activeRunId(target);
    if (!target.id || !runId || state.stopping) return;
    state.stopping = true;
    state.error = "";
    updateComposer();
    try {
      const run = await api.stopRun({ workspaceId: target.id, runId });
      state.finishedRunId = run.id;
      if (target.taskStatus?.monitoredRunId === run.id) {
        target.taskStatus = { ...target.taskStatus, ...describeTask(run) };
      }
      if (target.chatRunId !== run.id && run.status === "stopped") state.stopMessage = "Generation stopped.";
      if (workspace === target && target.taskStatus) updateTask(target.taskStatus);
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Could not stop generation.";
    } finally {
      state.stopping = false;
      if (workspace === target) {
        renderMessages();
        if (!collapsed && (document.activeElement === stop || document.activeElement === document.body)) input.focus();
      }
    }
  };
  form.onsubmit = async (event) => {
    event.preventDefault();
    const draft = input.value;
    const text = draft.trim();
    const target = workspace, state = sessionState(target);
    if (!text || state.pending || state.stopping || restoring.has(target)) return;
    if (!connection?.configured) { openKeyDialog(); return; }
    const provider = selectedProvider;
    const replyController = new AbortController();
    state.reply = replyController;
    state.pending = true;
    state.error = "";
    state.stopMessage = undefined;
    state.outgoing = text;
    target.draft = draft;
    input.value = "";
    window.clearTimeout(draftTimers.get(target));
    renderMessages();
    try {
      await persist(target);
      const reply = await api.chat([...target.messages.slice(-50), { role: "user", content: text }], replyController.signal,
        { provider, workspaceId: target.id, runId: target.chatRunId });
      state.reply = undefined;
      if (reply.runId) {
        target.chatRunId = reply.runId;
        target.chatCleared = false;
      }
      target.messages.push({ role: "user", content: text }, reply.message);
      state.outgoing = "";
      target.draft = "";
      await persist(target);
      if (workspace === target) {
        live.textContent = reply.message.content;
      }
    } catch (error) {
      if (replyController.signal.aborted) state.stopMessage = "Response stopped. Draft restored.";
      else state.error = error instanceof Error ? error.message : "Could not send your message. Please try again.";
      if (!replyController.signal.aborted && provider === selectedProvider && error instanceof ApiError && ["GEMINI_KEY_REQUIRED", "GEMINI_KEY_INVALID", "GROQ_KEY_REQUIRED", "GROQ_KEY_INVALID", "CODEX_LOGIN_REQUIRED"].includes(error.code)) {
        connectionVersion++;
        connection = { provider, configured: false, model: connection?.model ?? "" };
      }
    } finally {
      state.reply = undefined;
      state.pending = false;
      state.outgoing = "";
      if (workspace === target) {
        input.value = target.draft;
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
  const initialVersion = connectionVersion;
  void readChatProvider().catch(() => "gemini" as const).then(provider => {
    if (connectionVersion !== initialVersion) return;
    selectedProvider = provider;
    providerSelect.value = provider;
    void loadConnection();
  });
  return { selectWorkspace, updateTask };
}
