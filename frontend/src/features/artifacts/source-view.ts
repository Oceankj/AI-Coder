// Author: Ching Kao
// Student ID: 85768427
import { element } from "../../ui";
import { fileLanguage } from "./languages";
/** Token text remains inline in a real pre; the decorative gutter is a sibling. */
export async function renderSource(
  content: HTMLElement,
  source: string,
  path: string,
  isCurrent: () => boolean,
) {
  const pre = element("pre");
  pre.tabIndex = 0;
  pre.setAttribute("aria-label", "File source");
  const code = element("code", "", source || "(Empty file)");
  // A final BR gives the trailing newline a line box without adding source text.
  const preserveTrailingLine = () => {
    if (source.endsWith("\n") || source.endsWith("\r")) {
      const end = element("br");
      end.setAttribute("aria-hidden", "true");
      code.append(end);
    }
  };
  preserveTrailingLine();
  pre.append(code);
  content.replaceChildren(pre);
  const language = fileLanguage(path);
  if (
    !source ||
    !language ||
    new TextEncoder().encode(source).length > 100 * 1024 ||
    source.split("\n").length > 3000
  )
    return;
  try {
    const { highlightCode } = await import("./highlight");
    if (!isCurrent()) return;
    const result = await highlightCode(source, language);
    if (!isCurrent()) return;
    const fragment = document.createDocumentFragment(),
      gutter = element("span", "source-numbers");
    gutter.setAttribute("aria-hidden", "true");
    result.tokens.forEach((tokens, index) => {
      const number = element("span", "source-gutter");
      number.dataset.line = String(index + 1);
      gutter.append(number);
      const line = element("span", "source-line");
      line.dataset.line = String(index + 1);
      for (const token of tokens) {
        const span = element("span", "", token.content);
        if (token.color) span.style.color = token.color;
        if (token.fontStyle) {
          if (token.fontStyle & 1) span.style.fontStyle = "italic";
          if (token.fontStyle & 2) span.style.fontWeight = "bold";
          if (token.fontStyle & 4) span.style.textDecoration = "underline";
        }
        line.append(span);
      }
      fragment.append(line);
      if (index < result.tokens.length - 1)
        fragment.append(document.createTextNode("\n"));
    });
    code.replaceChildren(fragment);
    preserveTrailingLine();
    pre.prepend(gutter);
    pre.classList.add("highlighted-source");
    pre.dataset.language = language;
    pre.style.backgroundColor = result.bg ?? "";
    pre.style.color = result.fg ?? "";
  } catch {
    /* Keep already-rendered plaintext usable if a chunk or grammar fails. */
  }
}
