import { test, expect, type Page, type Route } from "@playwright/test";

type Message = { role: string; content: string };
async function chatBackend(page: Page, options: { workspaces?: boolean; reply?: (route: Route, messages: Message[]) => Promise<void> } = {}) {
  let configured = false;
  const histories: Message[][] = [];
  const keys: string[] = [];
  const workspaces = options.workspaces ? [{ id: "alpha", name: "Alpha" }, { id: "beta", name: "Beta" }] : [];
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/api/chat/config") {
      if (request.method() === "POST") { keys.push(request.postDataJSON().apiKey); configured = true; }
      return route.fulfill({ json: { configured, model: "test-gemini" } });
    }
    if (path === "/api/chat") {
      const messages = request.postDataJSON().messages;
      histories.push(messages);
      if (options.reply) return options.reply(route, messages);
      return route.fulfill({ json: { message: { role: "assistant", content: "Let's start with genres." }, model: "test-gemini", usage: { apiCalls: 1, inputTokens: 4, outputTokens: 8, totalTokens: 16 } } });
    }
    if (path === "/api/workspaces") return route.fulfill({ json: workspaces });
    if (/\/runs$/.test(path)) return route.fulfill({ json: [] });
    const workspace = workspaces.find(item => path === `/api/workspaces/${item.id}`);
    if (workspace) return route.fulfill({ json: { ...workspace, rootPath: `workspaces/${workspace.id}`, createdAt: "2026-11-20T00:00:00Z" } });
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "Unexpected test request" } } });
  });
  return { histories, keys };
}

async function addKey(page: Page) {
  await page.getByRole("button", { name: "Add API key", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Connect Gemini", exact: true });
  await expect(dialog.getByRole("link", { name: "Get an API key in Google AI Studio" })).toHaveAttribute("href", "https://aistudio.google.com/apikey");
  await expect(dialog.locator("input")).toHaveAttribute("type", "password");
  await dialog.getByLabel("Gemini API key", { exact: true }).fill("test-key-never-store");
  await dialog.getByRole("button", { name: "Use API key", exact: true }).click();
  await expect(dialog).not.toBeVisible();
}

test("guides key setup without a workspace and sends real chat payloads with history", async ({ page }) => {
  const backend = await chatBackend(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Let’s connect Gemini." })).toBeVisible();
  await addKey(page);
  const input = page.getByRole("textbox", { name: "Message draft" });
  await input.fill("Plan a playlist app");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".assistant-message")).toContainText("Let's start with genres.");
  await input.fill("What next?");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(2);
  expect(backend.histories[1]).toEqual([{ role: "user", content: "Plan a playlist app" }, { role: "assistant", content: "Let's start with genres." }, { role: "user", content: "What next?" }]);
  expect(backend.keys).toEqual(["test-key-never-store"]);
  expect(await page.locator("body").innerText()).not.toContain("test-key-never-store");
  expect(await page.locator("#gemini-key").inputValue()).toBe("");
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).not.toContain("test-key-never-store");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page.locator(".chat-message")).toHaveCount(0);
});

test("failed sends preserve drafts and retry without duplicate messages", async ({ page }) => {
  let attempts = 0;
  const backend = await chatBackend(page, { reply: async route => {
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 429, json: { error: { code: "GEMINI_RATE_LIMIT", message: "Gemini quota reached. Try again later." } } });
    return route.fulfill({ json: { message: { role: "assistant", content: "Ready now." }, model: "test-gemini", usage: { apiCalls: 1 } } });
  } });
  await page.goto("/");
  await addKey(page);
  const input = page.getByRole("textbox", { name: "Message draft" });
  await input.fill("Keep this message");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Gemini quota reached");
  await expect(input).toHaveValue("Keep this message");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".assistant-message")).toContainText("Ready now.");
  await expect(page.locator(".draft-message")).toHaveCount(1);
  expect(backend.histories[0]).toEqual(backend.histories[1]);
});

test("a late reply stays with its original workspace", async ({ page }) => {
  let resolveReply!: () => void;
  const pending = new Promise<void>(resolve => { resolveReply = resolve; });
  await chatBackend(page, { workspaces: true, reply: async route => {
    await pending;
    await route.fulfill({ json: { message: { role: "assistant", content: "Alpha reply" }, model: "test-gemini", usage: { apiCalls: 1 } } });
  } });
  await page.goto("/");
  await expect(page.locator(".chat-project")).toHaveText("Alpha");
  await addKey(page);
  await page.getByRole("textbox", { name: "Message draft" }).fill("Question about Alpha");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Beta", exact: true }).click();
  resolveReply();
  await expect(page.locator(".chat-project")).toHaveText("Beta");
  await expect(page.locator(".assistant-message")).toHaveCount(0);
  await page.getByRole("button", { name: "Alpha", exact: true }).click();
  await expect(page.locator(".assistant-message")).toContainText("Alpha reply");
});

test("a rejected key returns to setup and retains the unsent draft", async ({ page }) => {
  await chatBackend(page, { reply: route => route.fulfill({ status: 401, json: { error: { code: "GEMINI_KEY_INVALID", message: "Gemini rejected this API key. Check or replace it in settings." } } }) });
  await page.goto("/");
  await addKey(page);
  await page.getByRole("textbox", { name: "Message draft" }).fill("Do not lose this");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("button", { name: "Add API key", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message draft" })).toHaveValue("Do not lose this");
  await expect(page.getByRole("alert")).toContainText("rejected");
});

test("Enter sends once, Shift+Enter adds a newline, and reply dots respect reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  let releaseReply!: () => void;
  const pending = new Promise<void>(resolve => { releaseReply = resolve; });
  const backend = await chatBackend(page, { reply: async route => {
    await pending;
    await route.fulfill({ json: { message: { role: "assistant", content: "Got both lines." }, model: "test-gemini", usage: { apiCalls: 1 } } });
  } });
  await page.goto("/");
  await addKey(page);
  const input = page.getByRole("textbox", { name: "Message draft" });
  await input.fill("First line");
  await input.press("Shift+Enter");
  await input.pressSequentially("Second line");
  await expect(input).toHaveValue("First line\nSecond line");
  expect(backend.histories).toHaveLength(0);
  await input.press("Enter");
  const dots = page.locator(".typing-dots");
  await expect(dots).toBeVisible();
  await expect(input).toBeDisabled();
  await expect(page.locator(".chat-connection-status")).toContainText("Gemini is replying");
  await expect(dots).toHaveAttribute("aria-hidden", "true");
  await expect(dots.locator("span").first()).toHaveCSS("animation-name", "chat-typing");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(dots.locator("span").first()).toHaveCSS("animation-name", "none");
  releaseReply();
  await expect(page.locator(".assistant-message")).toContainText("Got both lines.");
  await expect(dots).toBeHidden();
  expect(backend.histories).toHaveLength(1);
  expect(backend.histories[0][0].content).toBe("First line\nSecond line");
});

test("IME confirmation and held Enter never submit; the next ordinary Enter sends Chinese text", async ({ page }) => {
  const backend = await chatBackend(page);
  await page.goto("/");
  await addKey(page);
  const input = page.getByRole("textbox", { name: "Message draft" });
  await input.fill("你好世界");
  const result = await input.evaluate(node => {
    let submitted = 0;
    node.closest("form")!.addEventListener("submit", () => { submitted++; });
    const enter = (options: KeyboardEventInit) => {
      const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...options });
      node.dispatchEvent(event);
      return event.defaultPrevented;
    };
    // Native composition flag, even without a compositionstart event.
    const nativePrevented = enter({ isComposing: true });
    node.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
    // Also protect IMEs that do not set isComposing on every keydown.
    const trackedPrevented = enter({ isComposing: false });
    node.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true, data: "你好世界" }));
    // Safari may deliver compositionend before its confirming Enter keydown.
    const safariPrevented = enter({ isComposing: false, keyCode: 229 });
    const repeatedPrevented = enter({ repeat: true });
    return { submitted, nativePrevented, trackedPrevented, safariPrevented, repeatedPrevented };
  });
  expect(result).toEqual({ submitted: 0, nativePrevented: false, trackedPrevented: false, safariPrevented: false, repeatedPrevented: true });
  await expect(input).toHaveValue("你好世界");
  await input.press("Enter");
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  expect(backend.histories).toHaveLength(1);
  expect(backend.histories[0]).toEqual([{ role: "user", content: "你好世界" }]);
});
