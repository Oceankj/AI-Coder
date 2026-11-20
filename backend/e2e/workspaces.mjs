// Scenario: workspaces are created, selected, and stored by the real backend.
import { createWorkspaceInUi, openApp, reporter } from "./common.mjs";

const { check, finish } = reporter("workspaces");
const { browser, page, consoleErrors, apiErrors, apiCalls } = await openApp();
await page.waitForTimeout(1000);
check(
  "workspace list comes from the backend",
  apiCalls.includes("GET /api/workspaces 200"),
  apiCalls.join(", "),
);

const created = await createWorkspaceInUi(page, "  Backend check  ");
check("the backend trims the name", created.name === "Backend check", created.name);
await page.waitForTimeout(800);
check(
  "the new workspace is selected",
  (await page.locator("#active-name").textContent()) === "Backend check",
);
const source = (await page.locator("#workspace-source").textContent()) ?? "";
check("rootPath is shown", source.endsWith(created.id), source);

await page.reload();
await page.waitForTimeout(1500);
const buttons = await page.getByRole("button", { name: "Backend check", exact: true }).count();
check("the workspace survives a page reload", buttons > 0);

check("no API errors", apiErrors.length === 0, apiErrors.join(", "));
check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
await browser.close();
finish();
