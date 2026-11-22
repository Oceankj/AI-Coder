// Author: Ching Kao
// Student ID: 85768427
// Exercise the production Coordinator and graph with scripted Google responses.
import assert from "node:assert/strict";
import { API, createWorkspaceInUi, openApp } from "./common.mjs";

const { browser, page, apiErrors } = await openApp();
try {
  const workspace = await createWorkspaceInUi(page, "Chat TDD");
  const send = page.getByRole("textbox", { name: "Message draft" });
  await send.fill("Build an adder");
  const reply = page.waitForResponse(r => new URL(r.url()).pathname === "/api/chat");
  await send.press("Enter");
  const { runId } = await (await reply).json();
  assert.ok(runId);
  await page.locator(".assistant-message").filter({ hasText: "All required tests passed" }).waitFor({ timeout: 60_000 });
  const base = `${API}/workspaces/${workspace.id}/runs/${runId}`;
  const run = await (await page.request.get(base)).json();
  assert.equal(run.checks.tests, "passed");
  assert.equal(run.status, "completed");
  const { events } = await (await page.request.get(base + "/events")).json();
  const checks = events.filter(e => e.type === "checks");
  assert.deepEqual(checks.map(e => e.message.match(/\((\w+)\)/)[1]), ["failed", "failed", "passed"]);
  await page.getByRole("button", { name: "add.cjs", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "add.cjs", exact: true });
  await preview.getByText(/exports\.add/, { exact: false }).last().waitFor();
  assert.match(await preview.textContent(), /a \+ b/);
  await page.keyboard.press("Escape");
  const zip = await page.request.get(base + "/download");
  assert.equal(zip.headers()["content-type"], "application/zip");
  assert.deepEqual(apiErrors, []);
  console.log("PASS  chat → Coordinator → Planner → Tester → Red → Coder → repair → Green → report → ZIP", runId);
  for (const check of checks) console.log(check.message);
} finally {
  await browser.close();
}
