// Author: Ching Kao
// Student ID: 85768427
import { setupWorker } from "msw/browser";
import { createHandlers } from "./handlers";

const raw = import.meta.glob("./fixtures/workspaces/**/*", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
const fixtures: Record<string, Record<string, string>> = {};
for (const [key, content] of Object.entries(raw)) {
  const [name, ...path] = key.slice("./fixtures/workspaces/".length).split("/");
  (fixtures[name] ??= {})[path.join("/")] = content;
}
export const worker = setupWorker(
  ...createHandlers({ fixtures, baseUrl: import.meta.env.VITE_API_BASE_URL || "/api" }),
);
