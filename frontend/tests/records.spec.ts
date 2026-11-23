// Author: Ching Kao
// Student ID: 85768427
import { test, expect } from "@playwright/test";

const record = {
  callId: "call-1", requestId: "request-1", startedAt: "2026-11-20T10:00:00Z", finishedAt: "2026-11-20T10:00:30Z",
  event: "completed", caller: "chat", role: null, model: "gemini-flash-latest", resolvedModel: "gemini-actual",
  status: 200, providerStatus: null, durationMs: 29654, providerMs: 29588, inputTokens: 79, outputTokens: 42, totalTokens: 158, errorCode: null,
};

test("records modal loads metadata, refreshes, and restores focus on Escape", async ({ page }) => {
  let records: Record<string, unknown>[] = [record];
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path === "/api/llm/records" ? records : path === "/api/chat/config" ? { configured: false, model: "test" } : [] });
  });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Call records", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "AI call records", exact: true });
  await expect(dialog.getByRole("cell", { name: "Completed · 200" })).toBeVisible();
  await expect(dialog.getByRole("cell", { name: "29.65 s", exact: true })).toBeVisible();
  await expect(dialog.getByRole("cell", { name: "158", exact: true })).toBeVisible();
  await expect(dialog.getByText("gemini-actual", { exact: false })).toBeVisible();
  await page.screenshot({ path: "/tmp/ai-records-desktop.png" });
  records = [{ ...record, event: "failed", status: 429, providerStatus: 429, errorCode: "GEMINI_RATE_LIMIT", durationMs: null, providerMs: null, inputTokens: null, outputTokens: null, totalTokens: null }];
  await dialog.getByRole("button", { name: "Refresh records" }).click();
  await expect(dialog.getByText("GEMINI_RATE_LIMIT")).toBeVisible();
  await expect(dialog.getByText("Provider HTTP 429")).toBeVisible();
  await expect(dialog.getByRole("cell", { name: "—", exact: true })).toHaveCount(5);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("records show retry and empty states, with table scrolling inside mobile dialog", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let state = "error";
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/llm/records") {
      return route.fulfill(state === "error" ? { status: 503, json: { error: { code: "RECORDS_UNAVAILABLE", message: "Could not read AI call records." } } } : { json: state === "empty" ? [] : [record] });
    }
    return route.fulfill({ json: path === "/api/chat/config" ? { configured: false, model: "test" } : [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Call records", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "AI call records", exact: true });
  await expect(dialog.getByRole("alert")).toContainText("Could not read");
  state = "empty";
  await dialog.getByRole("button", { name: "Retry loading records" }).click();
  await expect(dialog.getByText("No AI calls recorded yet.", { exact: false })).toBeVisible();
  state = "loaded";
  await dialog.getByRole("button", { name: "Refresh records" }).click();
  await expect(dialog.getByRole("table")).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  const scroll = dialog.getByRole("region", { name: "AI call records table" });
  expect(await scroll.evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
  await expect(dialog.getByRole("button", { name: "Close call records" })).toBeInViewport();
  await page.screenshot({ path: "/tmp/ai-records-mobile.png" });
});
