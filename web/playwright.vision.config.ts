import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", testMatch: "vision-settings.spec.ts", workers: 1, retries: 0, reporter: "line",
  outputDir: "../data/artifacts/p4b3-offline-20261025/browser-results",
  use: { baseURL: "http://127.0.0.1:8894" },
  webServer: { command: "npm run dev -- --port 8894 --strictPort", port: 8894, reuseExistingServer: false },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "narrow", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } },
  ],
});
