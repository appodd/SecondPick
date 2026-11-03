import fs from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const invocationDirectory = process.cwd();
const webDirectory = fs.existsSync(path.join(invocationDirectory, "web", "package.json"))
  ? path.join(invocationDirectory, "web")
  : invocationDirectory;
const repositoryRoot = path.resolve(webDirectory, "..");
const python = path.join(
  repositoryRoot,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python",
);
const serverScript = path.join(webDirectory, "e2e", "serve_e2e.py");

export default defineConfig({
  testDir: path.join(webDirectory, "e2e"),
  testMatch: ["p4-image-evidence.spec.ts", "market-generality.spec.ts", "p3-market.spec.ts", "evidence-research.spec.ts", "investigations.spec.ts", "workbench.spec.ts", "visual-qa.spec.ts", "conversation.spec.ts", "collection.spec.ts", "monitor.spec.ts", "projects.spec.ts", "onboarding.spec.ts", "product-media-logs.spec.ts", "status-language.spec.ts", "product-detail.spec.ts", "overview.spec.ts", "monitor-tasks.spec.ts", "ai-feedback.spec.ts", "market-analysis.spec.ts", "workspace-runtime.spec.ts", "goal-continuity.spec.ts", "settings-navigation.spec.ts", "product-insights.spec.ts", "research-followup.spec.ts"],
  fullyParallel: false,
  workers: 1, // Browser jobs are intentionally exclusive in the shared fixture database.
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:8876",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" "${serverScript}" --port 8876`,
    cwd: repositoryRoot,
    port: 8876,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  projects: [
    {
      name: "desktop-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile-chromium",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
