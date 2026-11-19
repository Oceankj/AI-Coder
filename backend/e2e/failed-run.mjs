// Scenario: a run fails and the UI shows why, without offering a download.
// Backend settings (set by run.sh): the placeholder Tester always fails and
// only one repair round is allowed.
import {
  API,
  createWorkspaceInUi,
  openApp,
  reporter,
  startRun,
  watchTaskStatus,
} from "./common.mjs";

const { check, finish } = reporter("run fails");
const { browser, page, consoleErrors } = await openApp();

const workspace = await createWorkspaceInUi(page, "Failure check");
await page.waitForTimeout(500);
const { run } = await startRun(page, workspace.id);

const seen = await watchTaskStatus(page);
const last = seen.at(-1) ?? "";
console.log(`  final status: ${last}`);
check("panel shows Failed", last.startsWith("Failed · "), last);
check(
  "panel shows the reason from the backend",
  last.includes("Feature 1 of 2 (Filter by genre)") && last.includes("no repair rounds are left"),
);

const detail = await (await page.request.get(`${API}/workspaces/${workspace.id}/runs/${run.id}`)).json();
check("run detail is failed", detail.status === "failed" && detail.checks.tests === "failed");
check("activeRole is cleared", detail.activeRole === null);

const download = await page.request.get(`${API}/workspaces/${workspace.id}/runs/${run.id}/download`);
check("download of a failed run is refused", download.status() === 409, String(download.status()));

const events = await (
  await page.request.get(`${API}/workspaces/${workspace.id}/runs/${run.id}/events?after=0`)
).json();
check(
  "feature 2 never started",
  !events.events.some((e) => e.message.startsWith("Feature 2/2 started")),
);

// The 409 above is expected; only check the page's own console.
check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
await browser.close();
finish();
