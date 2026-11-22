// Author: Ching Kao
// Student ID: 85768427
import { test, expect } from "@playwright/test";
import { fileLanguage } from "../src/features/artifacts/languages";
import { highlightCode } from "../src/features/artifacts/highlight";

test("loads every supported grammar and preserves source text", async () => {
  const examples = {
    "index.html": '<script>alert("preview")</script>',
    "styles.css": "body { color: red; }",
    "main.mjs": "const value = 1;",
    "types.ts": "const value: number = 1;",
    "App.jsx": "const App = () => <div>Hello</div>;",
    "App.tsx": "const App = () => <div>Hello</div>;",
    "main.py": 'def hello():\n    return "world"',
    "data.json": '{"value": 1}',
    "tsconfig.jsonc": '// comment\n{"value": 1}',
    "config.yml": "name: demo",
    "README.md": "# Heading\n\nText",
    "script.sh": 'echo "$PATH"',
    "Dockerfile.dev": "FROM node:22\nRUN npm install",
    "query.sql": "SELECT * FROM users;",
  };
  for (const [path, source] of Object.entries(examples)) {
    const language = fileLanguage(path);
    expect(language, path).toBeTruthy();
    const result = await highlightCode(source, language!);
    expect(
      result.tokens
        .map((line) => line.map((token) => token.content).join(""))
        .join("\n"),
      path,
    ).toBe(source);
    expect(
      result.tokens.flat().some((token) => token.color),
      path,
    ).toBe(true);
  }
  expect(fileLanguage("unknown.xyz")).toBeUndefined();
  expect(fileLanguage("notes.txt")).toBeUndefined();
  expect(fileLanguage("Dockerfile")).toBe("dockerfile");
});

test("modal lazily highlights HTML as inert source and switches languages", async ({
  page,
}) => {
  const chunks: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/artifacts/highlight.ts"))
      chunks.push(request.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: "index.html", exact: true }).waitFor();
  expect(chunks).toEqual([]);
  await page.getByRole("button", { name: "index.html", exact: true }).click();
  const pre = page.locator(".file-dialog pre");
  await expect(pre).toHaveAttribute("data-language", "html");
  await expect(pre.locator(".source-line").first()).toHaveAttribute(
    "data-line",
    "1",
  );
  await expect(pre.locator("script")).toHaveCount(0);
  expect(await pre.locator("code").textContent()).toContain("<script>");
  expect(chunks).toHaveLength(1);
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "requirements.md", exact: true })
    .click();
  await expect(pre).toHaveAttribute("data-language", "markdown");
});

test("blank source lines keep evenly spaced numbers without overlapping text", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "README.md", exact: true })
    .first()
    .click();
  const pre = page.locator('.file-dialog pre[data-language="markdown"]');
  await expect(pre).toBeVisible();
  const rows = await pre.locator(".source-gutter").evaluateAll((lines) =>
    lines.map((line) => {
      const box = line.getBoundingClientRect();
      return { y: box.y, height: box.height };
    }),
  );
  expect(rows.length).toBeGreaterThan(4);
  for (let i = 0; i < rows.length; i++) {
    expect(rows[i].height).toBeGreaterThan(20);
    if (i)
      expect(
        Math.abs(rows[i].y - rows[i - 1].y - rows[i - 1].height),
      ).toBeLessThan(1);
  }
  expect(await pre.locator("code").textContent()).toContain(
    "# Playlist Mixer\n\nAn interactive",
  );
  const copied = await pre.locator("code").evaluate((code) => {
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    return { source: code.textContent, selected: selection.toString() };
  });
  expect(copied.selected).toBe(copied.source);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(pre).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
});
