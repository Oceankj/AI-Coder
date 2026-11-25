// Author: Ching Kao; Student ID: 85768427
import type { WorkspaceFile } from "../workspaces/model";

// Resolve project assets through the existing file API, never against Canvas.
export async function preparePreviewDocument(html: string, files: WorkspaceFile[], signal: AbortSignal): Promise<string> {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const base = new URL("https://workspace.invalid/index.html");
  let bytes = 0;
  for (const node of doc.querySelectorAll<HTMLScriptElement | HTMLLinkElement>('script[src], link[rel~="stylesheet"][href]')) {
    const attr = node instanceof HTMLScriptElement ? "src" : "href";
    const url = new URL(node.getAttribute(attr)!, base);
    if (url.origin !== base.origin) continue;
    const path = decodeURIComponent(url.pathname.slice(1));
    const file = files.find(file => file.path === path);
    if (!file) throw new Error(`Preview asset is missing: ${path}`);
    bytes += file.size;
    if (bytes > 8 * 1024 * 1024) throw new Error("Preview assets exceed 8 MiB. Connect a project URL instead.");
    const text = await (await file.read(signal)).text();
    const type = attr === "src" ? "text/javascript" : "text/css";
    node.setAttribute(attr, `data:${type};charset=utf-8,${encodeURIComponent(text)}`);
  }
  return "<!doctype html>\n" + doc.documentElement.outerHTML;
}

const storagePrefix = "ai-coder-preview-v1:";
const maxStorageChars = 512 * 1024;
type Entries = [string, string][];

function validEntries(value: unknown): value is Entries {
  return Array.isArray(value) && value.length <= 1000 && value.every(pair =>
    Array.isArray(pair) && pair.length === 2 && pair.every(item => typeof item === "string")) &&
    JSON.stringify(value).length <= maxStorageChars;
}

// Runs inside the opaque sandbox. Only this workspace's storage is exposed.
function initializeStorage(initial: Entries, token: string, limit: number) {
  const data = new Map(initial);
  function commit(next: Map<string, string>) {
    const entries = [...next];
    if (next.size > 1000 || JSON.stringify(entries).length > limit)
      throw new DOMException("Preview storage quota exceeded.", "QuotaExceededError");
    data.clear();
    for (const [key, value] of next) data.set(key, value);
    parent.postMessage({ type: "ai-coder-preview-storage", token, entries }, "*");
  }
  Object.defineProperty(window, "localStorage", { value: {
    get length() { return data.size; },
    key(index: number) { return [...data.keys()][index] ?? null; },
    getItem(key: string) { return data.get(String(key)) ?? null; },
    setItem(key: string, value: string) { const next = new Map(data); next.set(String(key), String(value)); commit(next); },
    removeItem(key: string) { const next = new Map(data); next.delete(String(key)); commit(next); },
    clear() { commit(new Map()); },
  } });
}

export function mountPreviewDocument(frame: HTMLIFrameElement, html: string, workspaceId: string): () => void {
  const key = storagePrefix + workspaceId;
  const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
  const initial = validEntries(parsed) ? parsed : [];
  const token = crypto.randomUUID();
  const save = (event: MessageEvent) => {
    // All opaque origins serialize to "null"; source identity and a per-frame
    // token bind writes to this frame, not any other sandbox or workspace.
    if (event.source !== frame.contentWindow || event.origin !== "null" ||
        event.data?.type !== "ai-coder-preview-storage" || event.data.token !== token ||
        !validEntries(event.data.entries)) return;
    localStorage.setItem(key, JSON.stringify(event.data.entries));
  };
  const doc = new DOMParser().parseFromString(html, "text/html");
  const bootstrap = doc.createElement("script");
  const args = JSON.stringify([initial, token, maxStorageChars]).replace(/</g, "\\u003c");
  bootstrap.textContent = `(${initializeStorage.toString()})(...${args});`;
  doc.head.prepend(bootstrap);
  window.addEventListener("message", save);
  frame.srcdoc = "<!doctype html>\n" + doc.documentElement.outerHTML;
  return () => window.removeEventListener("message", save);
}
