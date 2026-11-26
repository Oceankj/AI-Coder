// Author: Ching Kao
// Student ID: 85768427
// Exercise the real UI, HTTP routes, gateway and Codex response normalization.
import assert from "node:assert/strict";
import { openApp } from "./common.mjs";

const { browser, page, apiErrors } = await openApp();
try {
  const provider = page.getByRole("combobox", { name: "Provider", exact: true });
  await provider.selectOption("codex");
  await page.getByRole("button", { name: "Recheck Codex login", exact: true }).waitFor();
  const input = page.getByRole("textbox", { name: "Message draft" });
  await input.fill("Hello Codex");
  const reply = page.waitForResponse(r => new URL(r.url()).pathname === "/api/chat");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  const response = await reply;
  assert.equal(response.status(), 200);
  assert.equal(response.request().postDataJSON().provider, "codex");
  const body = await response.json();
  assert.equal(body.message.content, "Hello from the Codex fixture.");
  assert.equal(body.usage.totalTokens, 10);
  await page.locator(".assistant-message").filter({ hasText: body.message.content }).waitFor();
  assert.equal(await page.locator('input[type="password"]').count(), 0);
  await page.reload();
  await page.waitForFunction(() => document.querySelector(".chat-provider select")?.value === "codex");
  await page.locator(".assistant-message").filter({ hasText: body.message.content }).waitFor();
  assert.deepEqual(apiErrors, []);
  console.log("PASS  Codex selection → real HTTP → shared gateway → normalized reply → reload");
} finally {
  await browser.close();
}
