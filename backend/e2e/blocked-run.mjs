// Author: Ching Kao
// Student ID: 85768427
import assert from "node:assert/strict";
import { API, createWorkspaceInUi, openApp } from "./common.mjs";

const { browser, page } = await openApp();
try {
  const workspace = await createWorkspaceInUi(page, "Blocked TDD");
  const send = page.getByRole("textbox", { name: "Message draft" });
  await send.fill("Build an adder");
  const reply = page.waitForResponse(r => new URL(r.url()).pathname === "/api/chat");
  await send.press("Enter");
  const { runId } = await (await reply).json();
  await page.locator(".assistant-message").filter({ hasText: "Repair budget exhausted" }).waitFor({ timeout: 60_000 });
  const base = `${API}/workspaces/${workspace.id}/runs/${runId}`;
  const detail = await (await page.request.get(base)).json();
  assert.equal(detail.status, "blocked");
  assert.equal(detail.activeRole, null);
  assert.equal(detail.checks.tests, "failed");
  assert.equal((await page.request.get(base + "/download")).status(), 409);
  console.log("PASS  chat reports exhausted repairs and blocks download");
} finally {
  await browser.close();
}
