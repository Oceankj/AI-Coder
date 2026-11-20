// Shared helpers for the browser checks in this folder.
//
// The checks drive the real frontend (Vite dev server, MSW off) against the
// real backend in a real browser. They borrow Playwright from the frontend's
// node_modules, so run `npm ci` in frontend/ once. See README.md.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND_DIR = process.env.FRONTEND_DIR ?? path.resolve(here, "../../frontend");
export const APP_URL = process.env.APP_URL ?? "http://127.0.0.1:5173/";
export const API = process.env.API_URL ?? "http://localhost:8000/api";

const require = createRequire(path.join(FRONTEND_DIR, "package.json"));
const { chromium } = require("@playwright/test");

/** Collects PASS/FAIL lines and sets the exit code at the end. */
export function reporter(scenario) {
  const results = [];
  console.log(`\n== ${scenario}`);
  return {
    check(name, ok, detail = "") {
      results.push(ok);
      console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
    },
    finish() {
      const failed = results.filter((ok) => !ok).length;
      console.log(`-- ${results.length - failed} passed, ${failed} failed`);
      process.exitCode = failed ? 1 : 0;
    },
  };
}

/**
 * Open the app in a browser and record problems while the page runs.
 *
 * Uses the installed Google Chrome by default (no browser download needed).
 * Set E2E_BROWSER_CHANNEL=bundled to use Playwright's own Chromium instead
 * (after `npx playwright install chromium` in frontend/).
 */
export async function openApp() {
  const channel = process.env.E2E_BROWSER_CHANNEL ?? "chrome";
  const browser = await chromium.launch(channel === "bundled" ? {} : { channel });
  const page = await browser.newPage();
  const consoleErrors = [];
  const apiErrors = [];
  const apiCalls = [];
  page.on("console", (message) => {
    // The Vite dev server has no favicon; that 404 is unrelated to the app.
    if (message.type() === "error" && !message.location().url.endsWith("/favicon.ico"))
      consoleErrors.push(`${message.text()} [${message.location().url}]`);
  });
  page.on("response", (response) => {
    if (response.url().startsWith(API))
      apiCalls.push(`${response.request().method()} ${new URL(response.url()).pathname} ${response.status()}`);
    if (response.url().startsWith(API) && response.status() >= 400)
      apiErrors.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  await page.goto(APP_URL);
  // Listeners are registered before navigating, so the first requests count.
  return { browser, page, consoleErrors, apiErrors, apiCalls };
}

/** Create a workspace through the UI, as a user would; returns the API response body. */
export async function createWorkspaceInUi(page, name) {
  await page.locator("#create-workspace").click();
  const dialog = page.getByRole("dialog", { name: "Create workspace", exact: true });
  await dialog.getByRole("textbox", { name: "Workspace name" }).fill(name);
  const response = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/workspaces" && r.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Create workspace", exact: true }).click();
  return (await response).json();
}

/**
 * Start a run through the API, as the frontend's createRun does. (The panel
 * cannot submit requirements yet; that is stage 4 frontend work.)
 */
export async function startRun(page, workspaceId) {
  const response = await page.request.post(`${API}/workspaces/${workspaceId}/runs`, {
    data: {
      description: "Music Playlist Mixer",
      requirements: ["Pick genres", "Smooth transitions"],
    },
  });
  return { status: response.status(), run: await response.json() };
}

/**
 * Watch the agent panel's task status (the title of .chat-task) until the run
 * ends; returns every distinct text seen, in order.
 */
export async function watchTaskStatus(page, timeoutMs = 60_000) {
  const seen = [];
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const text = await page.locator(".chat-task").getAttribute("title");
    if (text && text !== seen.at(-1)) seen.push(text);
    if (text?.includes("Completed") || text?.startsWith("Failed")) break;
    await page.waitForTimeout(150);
  }
  return seen;
}
