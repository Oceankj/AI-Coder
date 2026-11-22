// Author: Ching Kao
// Student ID: 85768427
import type { ChatMessage } from "../../types";

export interface TaskNotice {
  runId: string;
  state: "queued" | "running" | "blocked" | "completed" | "failed";
  text: string;
  afterMessageCount: number;
}

export interface ChatHistory {
  messages: ChatMessage[];
  notices: TaskNotice[];
  draft: string;
  chatRunId?: string;
  cleared?: boolean;
}

const databaseName = "ai-coder";
const storeName = "conversations";
const key = (workspaceId?: string) => workspaceId ?? "general";
const legacyKey = (workspaceId?: string) => `ai-coder-chat-v1:${key(workspaceId)}`;
let database: Promise<IDBDatabase> | undefined;
const writes = new Map<string, Promise<void>>();

function openDatabase(): Promise<IDBDatabase> {
  if (!database) {
    database = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(storeName);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Chat database is blocked by another tab."));
    }).catch(error => {
      database = undefined;
      throw error;
    });
  }
  return database;
}

function validHistory(value: unknown): ChatHistory | undefined {
  if (!value || typeof value !== "object") return;
  const history = value as Partial<ChatHistory>;
  if (!Array.isArray(history.messages) || !Array.isArray(history.notices)) return;
  if (!history.messages.every(message =>
    message && (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string"
  )) return;
  if (!history.notices.every(notice =>
    notice && typeof notice.runId === "string" && typeof notice.text === "string" &&
    Number.isInteger(notice.afterMessageCount) && notice.afterMessageCount >= 0 &&
    ["queued", "running", "blocked", "completed", "failed"].includes(notice.state)
  )) return;
  return {
    messages: history.messages,
    notices: history.notices,
    draft: typeof history.draft === "string" ? history.draft : "",
    chatRunId: typeof history.chatRunId === "string" ? history.chatRunId : undefined,
    cleared: history.cleared === true,
  };
}

async function readRecord(id: string): Promise<unknown> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = db.transaction(storeName, "readonly").objectStore(storeName).get(id);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function writeRecord(id: string, history: ChatHistory): Promise<void> {
  const db = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(storeName, "readwrite");
    transaction.objectStore(storeName).put(history, id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

export async function readChatHistory(workspaceId?: string): Promise<ChatHistory | undefined> {
  const id = key(workspaceId);
  await writes.get(id);
  const saved = validHistory(await readRecord(id));
  if (saved) return saved;

  // Move conversations saved by the earlier localStorage implementation once.
  const old = localStorage.getItem(legacyKey(workspaceId));
  if (!old) return;
  let history: ChatHistory | undefined;
  try { history = validHistory(JSON.parse(old)); } catch { return; }
  if (!history) return;
  await writeRecord(id, history);
  localStorage.removeItem(legacyKey(workspaceId));
  return history;
}

export function saveChatHistory(workspaceId: string | undefined, history: ChatHistory): Promise<void> {
  const id = key(workspaceId);
  const snapshot: ChatHistory = {
    messages: history.messages.map(message => ({ ...message })),
    notices: history.notices.map(notice => ({ ...notice })),
    draft: history.draft,
    chatRunId: history.chatRunId,
    cleared: history.cleared,
  };
  const next = (writes.get(id) ?? Promise.resolve())
    .catch(() => undefined)
    .then(() => writeRecord(id, snapshot));
  writes.set(id, next);
  void next.finally(() => { if (writes.get(id) === next) writes.delete(id); }).catch(() => undefined);
  return next;
}
