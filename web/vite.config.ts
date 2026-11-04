import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
        configure(proxy) {
          // Preserve the browser's local origin, including its port. The backend
          // still rejects non-loopback hosts and cross-origin write requests.
          proxy.on("proxyReq", (proxyReq, request) => {
            if (request.headers.host) proxyReq.setHeader("host", request.headers.host);
          });
        },
      },
    },
  },
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
