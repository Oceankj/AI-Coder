// Scenario: a run completes (with one repair) and its output reaches the UI.
// Backend settings (set by run.sh): placeholder Tester fails its first task.
import {
  API,
  createWorkspaceInUi,
  openApp,
  reporter,
  startRun,
  watchTaskStatus,
} from "./common.mjs";

const { check, finish } = reporter("run completes");
const { browser, page, consoleErrors, apiErrors } = await openApp();

const workspace = await createWorkspaceInUi(page, "Run check");
await page.waitForTimeout(500);
const { status, run } = await startRun(page, workspace.id);
check("run created as queued", status === 201 && run.status === "queued", `${status} ${run.status}`);

const seen = await watchTaskStatus(page);
console.log(`  status texts: ${seen.join("  ->  ")}`);
check("panel shows agents working", seen.some((t) => /^(Planner|Coder|Tester) · /.test(t)));
check("panel ends with Completed", (seen.at(-1) ?? "").includes("Completed"), seen.at(-1));

const events = await (
  await page.request.get(`${API}/workspaces/${workspace.id}/runs/${run.id}/events?after=0`)
).json();
const types = events.events.map((e) => e.type);
check("events include a repair", types.includes("repair"));
check(
  "events report both features",
  types.filter((t) => t === "feature_completed").length === 2,
);

await page.waitForTimeout(3500); // one watcher cycle refreshes the artifacts
const file = page.getByRole("button", { name: "playlist.js", exact: true });
check("generated files are listed in the sidebar", (await file.count()) > 0);
if (await file.count()) {
  await file.first().click();
  const dialog = page.getByRole("dialog", { name: "playlist.js", exact: true });
  await dialog.waitFor({ timeout: 5000 }).catch(() => {});
  check("file preview shows the code", ((await dialog.textContent()) ?? "").includes("generatePlaylist"));
  await page.keyboard.press("Escape");
}

const heading = await page.frameLocator("iframe").getByRole("heading", { name: "Playlist Mixer" }).count();
check("index.html is rendered in the preview", heading > 0);

const download = await page.request.get(`${API}/workspaces/${workspace.id}/runs/${run.id}/download`);
check(
  "download returns a ZIP",
  download.status() === 200 && download.headers()["content-type"] === "application/zip",
);

check("no API errors", apiErrors.length === 0, apiErrors.join(", "));
check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
await browser.close();
finish();
