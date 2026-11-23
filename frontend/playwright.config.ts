// Author: Ching Kao
// Student ID: 85768427
import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  use: { baseURL: "http://127.0.0.1:15175", ...devices["Desktop Chrome"] },
  projects: [
    { name: "development", testIgnore: /(?:regressions|chat|records).spec.ts/ },
    {
      name: "production",
      testMatch: /(?:regressions|chat|records).spec.ts/,
      use: { baseURL: "http://127.0.0.1:14175" },
    },
  ],
  webServer: [
    {
      command: "npm run dev -- --port 15175 --strictPort",
      url: "http://127.0.0.1:15175",
      env: { VITE_ENABLE_MSW: "true", VITE_API_BASE_URL: "/api" },
      reuseExistingServer: false,
    },
    {
      command: "npm run build && npm run preview -- --port 14175 --strictPort",
      url: "http://127.0.0.1:14175",
      env: { VITE_ENABLE_MSW: "false", VITE_API_BASE_URL: "/api" },
      reuseExistingServer: false,
    },
  ],
});
