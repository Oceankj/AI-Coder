import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

// Only these grammars and one theme become lazy chunks. No full Shiki bundle.
const grammars = {
  html: () => import("shiki/langs/html.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  javascript: () => import("shiki/langs/javascript.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  jsx: () => import("shiki/langs/jsx.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  python: () => import("shiki/langs/python.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  jsonc: () => import("shiki/langs/jsonc.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
  bash: () => import("shiki/langs/bash.mjs"),
  dockerfile: () => import("shiki/langs/dockerfile.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
};
const theme = "github-dark";
let instance: ReturnType<typeof createHighlighterCore> | undefined;
const loading = new Map<string, Promise<void>>();
export async function highlightCode(source: string, language: string) {
  if (!Object.hasOwn(grammars, language))
    throw new Error("Unsupported language");
  instance ??= createHighlighterCore({
    themes: [import("shiki/themes/github-dark.mjs")],
    langs: [],
    engine: createJavaScriptRegexEngine(),
  }).catch((error) => {
    instance = undefined;
    throw error;
  });
  const highlighter = await instance;
  if (!loading.has(language)) {
    const pending = highlighter
      .loadLanguage(grammars[language as keyof typeof grammars]())
      .catch((error) => {
        loading.delete(language);
        throw error;
      });
    loading.set(language, pending);
  }
  await loading.get(language);
  return highlighter.codeToTokens(source, { lang: language, theme });
}
