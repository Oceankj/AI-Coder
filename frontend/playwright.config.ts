import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  use: { baseURL: "http://127.0.0.1:5173", ...devices["Desktop Chrome"] },
  projects: [
    { name: "development", testIgnore: /regressions.spec.ts/ },
    {
      name: "production",
      testMatch: /regressions.spec.ts/,
      use: { baseURL: "http://127.0.0.1:4173" },
    },
  ],
  webServer: [
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run build && npm run preview -- --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
    },
  ],
});
