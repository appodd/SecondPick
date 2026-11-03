import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    emptyOutDir: true,
    outDir: "../src/shopping_agent/web/static",
  },
  test: {
    environment: "jsdom",
    include: ["web/src/**/*.{test,spec}.{ts,tsx}"],
    exclude: [...configDefaults.exclude, "web/e2e/**"],
    root: "..",
    setupFiles: "./web/src/test/setup.ts",
  },
});
