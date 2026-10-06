import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// React's `act` (used by @testing-library/react) only exists in the development
// build. Some shells/CI export NODE_ENV=production, which would otherwise make
// React resolve to its production build and break rendering tests. Force the
// test build before Vite resolves anything.
process.env.NODE_ENV = "development";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      // Route-driven components are tested against an in-memory router.
      {
        find: /^next\/navigation$/,
        replacement: fileURLToPath(new URL("./src/test/next-navigation.ts", import.meta.url)),
      },
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
    ],
  },
  define: {
    "process.env.NODE_ENV": JSON.stringify("development"),
  },
  optimizeDeps: {
    esbuildOptions: {
      define: { "process.env.NODE_ENV": JSON.stringify("development") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Several tests execute the real Python bridge (a subprocess per run), so run
    // files sequentially to avoid resource contention and flaky timeouts.
    fileParallelism: false,
    testTimeout: 180_000,
    hookTimeout: 180_000,
  },
});
