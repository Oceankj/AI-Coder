// Author: Ching Kao
// Student ID: 85768427
import { test, expect } from "@playwright/test";

test("browses real files, restores modal focus, and runs the embedded UI", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByRole("button", { name: "requirements.md", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("require at least two playlists");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "requirements.md", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Collapse conversation panel", exact: true })
    .click();
  const frame = page.frameLocator("iframe");
  await frame.getByRole("button", { name: /Golden hour/ }).click();
  await frame.getByRole("button", { name: "Create a mix" }).click();
  await expect(frame.getByRole("status")).toContainText(
    "Slow mornings + Golden hour",
  );
  await page
    .getByRole("button", { name: "Collapse playlist-mixer", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "requirements.md", exact: true }),
  ).not.toBeVisible();
  await page
    .getByRole("button", { name: "Collapse Workspaces", exact: true })
    .click();
  await expect(page.getByRole("complementary")).not.toBeVisible();
  await page
    .getByRole("button", { name: "Expand Workspaces", exact: true })
    .click();
  await expect(page.getByRole("complementary")).toBeVisible();
  expect(errors).toEqual([]);
});

test("isolates drafts and preview URLs when switching workspaces", async ({
  page,
}) => {
  await page.route("https://example.test/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>Connected project</h1>",
    }),
  );
  await page.goto("/");
  await expect(page.locator(".chat-project")).toHaveText("playlist-mixer");
  await page
    .getByRole("textbox", { name: "Message draft" })
    .fill("Unsent follow-up");
  await page
    .getByRole("button", { name: "project-notes", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Message draft" }),
  ).toBeEmpty();
  await expect(page.locator(".draft-message")).toHaveCount(0);
  await expect(page.locator("iframe")).toHaveCount(0);
  await page.getByRole("button", { name: "Set preview URL" }).click();
  await page
    .getByRole("textbox", { name: "Preview URL", exact: true })
    .fill("ftp://example.test/app");
  await page
    .getByRole("button", { name: "Connect preview", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("HTTP or HTTPS");
  await page
    .getByRole("textbox", { name: "Preview URL", exact: true })
    .fill("https://example.test/app");
  await page
    .getByRole("button", { name: "Connect preview", exact: true })
    .click();
  await expect(page.locator("iframe")).toHaveAttribute(
    "src",
    "https://example.test/app",
  );
  await page
    .getByRole("button", { name: "playlist-mixer", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Message draft" }),
  ).toHaveValue("Unsent follow-up");
  await expect(page.locator(".draft-message")).toHaveCount(0);
  await expect(page.locator("iframe")).not.toHaveAttribute("src");
  await page
    .getByRole("button", { name: "project-notes", exact: true })
    .click();
  await expect(page.locator("iframe")).toHaveAttribute(
    "src",
    "https://example.test/app",
  );
});

test("moves, resizes, collapses, and keeps the panel reachable on mobile", async ({
  page,
}) => {
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Agent conversation panel" });
  await expect(panel).toBeVisible();
  const initial = (await panel.boundingBox())!;
  const drag = page.getByRole("button", {
    name: "Move panel (use arrow keys)",
    exact: true,
  });
  const handle = (await drag.boundingBox())!;
  await page.mouse.move(handle.x + 10, handle.y + 10);
  await page.mouse.down();
  await page.mouse.move(handle.x - 180, handle.y + 50, { steps: 8 });
  await page.mouse.up();
  expect((await panel.boundingBox())!.x).toBeLessThan(initial.x - 100);
  await drag.focus();
  await page.keyboard.press("ArrowLeft");
  const resize = page.getByRole("button", {
    name: "Resize panel (use arrow keys)",
    exact: true,
  });
  const beforeResize = (await panel.boundingBox())!;
  const corner = (await resize.boundingBox())!;
  await page.mouse.move(corner.x + 10, corner.y + 10);
  await page.mouse.down();
  await page.mouse.move(corner.x + 80, corner.y + 40, { steps: 8 });
  await page.mouse.up();
  expect((await panel.boundingBox())!.width).toBeGreaterThan(
    beforeResize.width,
  );
  await page
    .getByRole("button", { name: "Collapse conversation panel", exact: true })
    .click();
  expect((await panel.boundingBox())!.height).toBe(40);
  await page
    .getByRole("button", { name: "Expand conversation panel", exact: true })
    .click();
  expect((await panel.boundingBox())!.height).toBeGreaterThan(340);
  await page.setViewportSize({ width: 390, height: 640 });
  await expect
    .poll(async () => {
      const bounds = (await panel.boundingBox())!;
      return bounds.x + bounds.width;
    })
    .toBeLessThanOrEqual(390);
  const mobile = (await panel.boundingBox())!;
  expect(mobile.x).toBeGreaterThanOrEqual(0);
  expect(mobile.y).toBeGreaterThanOrEqual(0);
  expect(mobile.x + mobile.width).toBeLessThanOrEqual(390);
  expect(mobile.y + mobile.height).toBeLessThanOrEqual(640);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await expect(panel.getByRole("combobox")).toHaveCount(0);
  await expect(page.locator(".moving-panel")).toHaveCount(0);
});

test("creates a workspace through the API and selects the server result", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator("#create-workspace").click();
  const dialog = page.getByRole("dialog", {
    name: "Create workspace",
    exact: true,
  });
  await dialog
    .getByRole("textbox", { name: "Workspace name" })
    .fill("  My new project  ");
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/workspaces" &&
      response.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.request().postDataJSON()).toEqual({ name: "My new project" });
  expect(response.status()).toBe(201);
  expect(response.fromServiceWorker()).toBe(true);
  const created = await response.json();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator("#active-name")).toHaveText(created.name);
  await expect(page.locator("#workspace-source")).toHaveText(
    `workspaces/${created.id}`,
  );
  await expect(
    page.getByRole("button", { name: created.name, exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByText("No generated files yet", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(
    await page.evaluate(async () => (await fetch("/api/workspaces")).json()),
  ).toContainEqual(created);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
});

test("rejects blank names and closing the form does not create a workspace", async ({
  page,
}) => {
  const creates: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/workspaces"
    )
      creates.push(request.url());
  });
  await page.goto("/");
  await page.locator("#create-workspace").click();
  const dialog = page.getByRole("dialog", {
    name: "Create workspace",
    exact: true,
  });
  const name = dialog.getByRole("textbox", { name: "Workspace name" });
  await name.fill("   ");
  await dialog
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(name).toBeFocused();
  await expect(name).toHaveAttribute("aria-invalid", "true");
  await name.fill("Not created");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  expect(creates).toEqual([]);
  await expect(
    page.getByRole("button", { name: "Not created", exact: true }),
  ).toHaveCount(0);
});

test("loads workspace and file content through the browser MSW worker", async ({
  page,
}) => {
  const responses: { path: string; mocked: boolean }[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/api/"))
      responses.push({ path, mocked: response.fromServiceWorker() });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "requirements.md", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "require at least two playlists",
  );
  expect(
    responses.some(
      (response) => response.path === "/api/workspaces" && response.mocked,
    ),
  ).toBe(true);
  expect(
    responses.some(
      (response) => response.path.endsWith("/runs") && response.mocked,
    ),
  ).toBe(true);
  expect(
    responses.some(
      (response) => response.path.endsWith("/files") && response.mocked,
    ),
  ).toBe(true);
  expect(
    responses.some(
      (response) => response.path.endsWith("/file") && response.mocked,
    ),
  ).toBe(true);
});

test("switching before a workspace load finishes never restores stale files", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "playlist-mixer", exact: true })
    .waitFor();
  await page
    .getByRole("button", { name: "project-notes", exact: true })
    .click();
  await page.getByRole("button", { name: "ideas.md", exact: true }).waitFor();
  await expect(page.locator("#active-name")).toHaveText("project-notes");
  await expect(page.locator("iframe")).toHaveCount(0);
  await page
    .getByRole("button", { name: "playlist-mixer", exact: true })
    .click();
  await page
    .getByRole("button", { name: "requirements.md", exact: true })
    .waitFor();
  await expect(page.locator("iframe")).toHaveAttribute(
    "title",
    "playlist-mixer project UI",
  );
});

test("drags the panel by its title and collapsed header while keeping collapse clickable", async ({
  page,
}) => {
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Agent conversation panel" });
  await expect(panel).toBeVisible();
  const initial = (await panel.boundingBox())!;
  const title = (await panel.locator(".chat-heading").boundingBox())!;
  await page.mouse.move(title.x + 20, title.y + 8);
  await page.mouse.down();
  await page.mouse.move(title.x - 100, title.y + 68, { steps: 6 });
  await page.mouse.up();
  const moved = (await panel.boundingBox())!;
  expect(moved.x).toBeLessThan(initial.x - 100);
  expect(moved.y).toBeGreaterThan(initial.y + 40);
  await page
    .getByRole("button", { name: "Collapse conversation panel", exact: true })
    .click();
  expect((await panel.boundingBox())!.height).toBe(40);
  const header = (await panel.locator(".chat-header").boundingBox())!;
  await page.mouse.move(header.x + 180, header.y + 18);
  await page.mouse.down();
  await page.mouse.move(header.x + 120, header.y + 58, { steps: 6 });
  await page.mouse.up();
  expect((await panel.boundingBox())!.x).toBeLessThan(moved.x - 40);
  await page
    .getByRole("button", { name: "Expand conversation panel", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Message draft" }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toHaveClass(/moving-panel/);
});

test("collapsed header retains the project and workspace-scoped task status", async ({
  page,
}) => {
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Agent conversation panel" });
  await expect(panel.locator(".chat-project")).toHaveText("playlist-mixer");
  await expect(panel.locator(".chat-task")).toHaveText(
    "No active task · Completed",
  );
  await page
    .getByRole("button", { name: "Collapse conversation panel", exact: true })
    .click();
  await expect(panel.locator(".chat-project")).toBeVisible();
  await expect(panel.locator(".chat-task")).toBeVisible();
  await expect(panel.locator(".chat-task")).toHaveText("No active task · Completed");
  await expect(page.locator(".workspace-count")).toHaveCount(0);

  expect((await panel.boundingBox())!.height).toBe(40);
  await page
    .getByRole("button", { name: "project-notes", exact: true })
    .click();
  await expect(panel.locator(".chat-project")).toHaveText("project-notes");
  await expect(panel.locator(".chat-task")).toHaveText(
    "No active task · Completed",
  );
  await expect(
    page.getByRole("button", {
      name: "Expand conversation panel",
      exact: true,
    }),
  ).toBeVisible();
});

test("completed workspace downloads its generated ZIP", async ({ page }) => {
  await page.goto("/");
  const button = page.getByRole("button", { name: "Download ZIP" });
  await expect(button).toBeVisible();
  const download = page.waitForEvent("download");
  await button.click();
  expect((await download).suggestedFilename()).toBe("run-1.zip");
});

test("file preview closes on backdrop clicks and keeps content clicks open", async ({
  page,
}) => {
  await page.goto("/");
  const file = page.getByRole("button", {
    name: "requirements.md",
    exact: true,
  });
  await file.click();
  const dialog = page.getByRole("dialog", {
    name: "requirements.md",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  await dialog.locator(".file-meta").click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(3, 3);
  await expect(dialog).not.toBeVisible();
  await expect(file).toBeFocused();
});
