// Author: Ching Kao
// Student ID: 85768427
import "./styles.css";
import { element, button } from "./ui";
async function bootstrap() {
  try {
    // Keep fixture modules out of production and await interception before any fetch.
    if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW !== "false") {
      const { worker } = await import("./mocks/browser");
      await worker.start({
        onUnhandledRequest(request, print) {
          const apiBase = new URL(
            import.meta.env.VITE_API_BASE_URL || "/api",
            location.origin,
          );
          const url = new URL(request.url);
          if (
            url.origin === apiBase.origin &&
            url.pathname.startsWith(`${apiBase.pathname.replace(/\/$/, "")}/`)
          )
            print.error();
        },
      });
    }
    await import("./app");
  } catch (error) {
    const root = document.querySelector<HTMLDivElement>("#app")!;
    const message = element(
      "p",
      "",
      error instanceof Error ? error.message : "Startup failed",
    );
    const retry = button("Reload", "refresh", "primary-button");
    retry.onclick = () => location.reload();
    root.replaceChildren(
      element("h1", "", "Unable to start Canvas"),
      message,
      retry,
    );
  }
}
void bootstrap();
