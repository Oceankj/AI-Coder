// Author: Ching Kao
// Student ID: 85768427
import { api } from "../../api/client";
import { createDialog } from "../../components/dialog";
import { latestRequest } from "../../core/latest-request";
import { button, element } from "../../ui";
import type { AICallRecord } from "../../types";

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "medium" });
const number = new Intl.NumberFormat();
const duration = (ms: number | null) => ms === null ? "—" : `${(ms / 1000).toFixed(2)} s`;
const tokens = (value: number | null) => value === null ? "—" : number.format(value);

export function createCallRecordsDialog() {
  const { dialog } = createDialog({
    id: "call-records-title", title: "AI call records", closeLabel: "Close call records",
    className: "records-dialog", icon: "file", lightDismiss: true,
  });
  const toolbar = element("div", "records-toolbar");
  const hint = element("p", "", "Recent chat and agent calls · times shown in your timezone");
  const refresh = button("Refresh records", "refresh", "suggestion");
  toolbar.append(hint, refresh);
  const content = element("div", "records-content");
  dialog.append(toolbar, content);
  const requests = latestRequest();
  dialog.addEventListener("close", requests.cancel);

  function cell(row: HTMLTableRowElement, text: string, className = "") {
    const node = element("td", className, text);
    row.append(node);
    return node;
  }
  function render(records: AICallRecord[]) {
    content.replaceChildren();
    if (!records.length) {
      content.append(element("p", "records-empty", "No AI calls recorded yet. Send a chat message, then refresh."));
      return;
    }
    const scroll = element("div", "records-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "AI call records table");
    const table = element("table", "records-table");
    table.append(element("caption", "", `Latest ${records.length} recorded call${records.length === 1 ? "" : "s"}. “—” means not reported; “Started” means no completion is recorded yet.`));
    const head = element("thead"), header = element("tr");
    for (const label of ["Time", "Result", "Source", "Model", "Total time", "Gemini time", "Input tokens", "Output tokens", "Total tokens", "Request ID"]) {
      const th = element("th", "", label);
      th.scope = "col";
      header.append(th);
    }
    head.append(header);
    const body = element("tbody");
    for (const record of records) {
      const row = element("tr");
      const timestamp = record.startedAt ?? record.finishedAt;
      const time = cell(row, "");
      if (timestamp) {
        const value = element("time", "", dateTime.format(new Date(timestamp)));
        value.dateTime = timestamp;
        time.append(value);
      } else time.textContent = "—";
      const result = cell(row, "");
      const label = { started: "Started", completed: "Completed", failed: "Failed", cancelled: "Cancelled" }[record.event];
      const badge = element("span", "record-state", `${label}${record.status === null ? "" : ` · ${record.status}`}`);
      badge.dataset.state = record.event;
      result.append(badge);
      if (record.errorCode) result.append(element("small", "record-detail", record.errorCode));
      if (record.providerStatus !== null) result.append(element("small", "record-detail", `Provider HTTP ${record.providerStatus}`));
      cell(row, record.caller === "chat" ? "Chat" : record.role ?? "Agent");
      const model = cell(row, record.resolvedModel ?? record.model ?? "—", "record-model");
      if (record.model && record.resolvedModel && record.model !== record.resolvedModel) model.append(element("small", "record-detail", record.model));
      cell(row, duration(record.durationMs), "record-number");
      cell(row, duration(record.providerMs), "record-number");
      cell(row, tokens(record.inputTokens), "record-number");
      cell(row, tokens(record.outputTokens), "record-number");
      cell(row, tokens(record.totalTokens), "record-number");
      const id = cell(row, "");
      id.append(element("code", "record-id", record.requestId ?? record.callId));
      body.append(row);
    }
    table.append(head, body);
    scroll.append(table);
    content.append(scroll);
  }
  async function load() {
    const request = requests.start();
    refresh.disabled = true;
    content.setAttribute("aria-busy", "true");
    const loading = element("p", "records-empty", "Loading call records…");
    loading.setAttribute("role", "status");
    content.replaceChildren(loading);
    try {
      const records = await api.aiCallRecords(request.signal);
      if (request.isCurrent() && dialog.open) render(records);
    } catch (error) {
      if (!request.isCurrent() || !dialog.open) return;
      const message = element("p", "records-empty", error instanceof Error ? error.message : "Could not load call records.");
      message.setAttribute("role", "alert");
      const retry = button("Retry loading records", "refresh", "suggestion");
      retry.onclick = () => { void load(); };
      content.replaceChildren(message, retry);
    } finally {
      if (request.isCurrent()) {
        refresh.disabled = false;
        content.removeAttribute("aria-busy");
      }
    }
  }
  refresh.onclick = () => { void load(); };
  return {
    open() {
      if (!dialog.open) dialog.showModal();
      void load();
    },
  };
}
