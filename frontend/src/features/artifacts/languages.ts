// Author: Ching Kao
// Student ID: 85768427
/** Explicit language selection avoids guessing on config and unknown files. */
const extensions: Record<string, string> = {
  html: "html",
  htm: "html",
  css: "css",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  mts: "typescript",
  cts: "typescript",
  jsx: "jsx",
  tsx: "tsx",
  py: "python",
  pyw: "python",
  json: "json",
  jsonc: "jsonc",
  yaml: "yaml",
  yml: "yaml",
  md: "markdown",
  markdown: "markdown",
  sh: "bash",
  bash: "bash",
  sql: "sql",
};
export function fileLanguage(path: string): string | undefined {
  const name = path.split("/").at(-1)!.toLowerCase();
  if (
    name === "dockerfile" ||
    name.startsWith("dockerfile.") ||
    name.endsWith(".dockerfile")
  )
    return "dockerfile";
  if (name === ".bashrc" || name === ".bash_profile") return "bash";
  return extensions[name.split(".").at(-1)!];
}
