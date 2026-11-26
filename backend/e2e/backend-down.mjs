// Scenario: the backend is not running. The frontend must say so and offer a
// retry, never fall back to sample data (frontend/README.md: "There is no
// fallback to sample data on backend failures").
import { openApp, reporter } from "./common.mjs";

const { check, finish } = reporter("backend down");
const { browser, page } = await openApp();
await page.getByRole("button", { name: "Retry loading workspaces", exact: true }).waitFor();

const retry = page.getByRole("button", { name: "Retry" });
check("a Retry button is shown", (await retry.count()) > 0);
const sample = await page.getByRole("button", { name: "playlist-mixer", exact: true }).count();
check("no MSW sample workspaces appear", sample === 0);
// The Retry button itself sits in the workspace list; nothing else may.
const names = await page.locator("#workspace-list button").allTextContents();
const others = names.map((n) => n.trim()).filter((n) => !n.startsWith("Retry"));
check("the workspace list shows no workspaces", others.length === 0, `buttons: ${names.join(", ")}`);

await browser.close();
finish();
