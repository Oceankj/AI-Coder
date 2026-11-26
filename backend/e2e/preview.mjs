// Author: Ching Kao
// Student ID: 85768427
// Real preview API, local HTTP assets, module imports and browser storage.
import assert from "node:assert/strict";
import { openApp } from "./common.mjs";

const { browser, page, apiErrors } = await openApp();
try {
  const frame = page.frameLocator("iframe");
  await frame.getByRole("heading", { name: "Preview integration" }).waitFor();
  assert.equal(await frame.getByRole("heading").evaluate(node => getComputedStyle(node).color), "rgb(12, 34, 56)");
  await frame.getByText("Ready", { exact: true }).waitFor();
  await frame.getByRole("button", { name: "Save playlist", exact: true }).click();
  await frame.getByText("Saved playlist", { exact: true }).waitFor();
  const previewUrl = await page.locator("iframe").getAttribute("src");
  assert.equal(new URL(previewUrl).hostname, "127.0.0.1");
  assert.notEqual(new URL(previewUrl).origin, new URL(page.url()).origin);
  await page.reload();
  await frame.getByText("Saved playlist", { exact: true }).waitFor();
  assert.equal(await page.locator("iframe").getAttribute("src"), previewUrl);
  await page.getByRole("button", { name: "Reload preview", exact: true }).click();
  await frame.getByText("Saved playlist", { exact: true }).waitFor();
  assert.deepEqual(apiErrors, []);
  console.log("PASS  real preview API → HTTP HTML/CSS/modules → native storage → reload");
} finally {
  await browser.close();
}
