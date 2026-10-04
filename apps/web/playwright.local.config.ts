import { defineConfig, devices } from "@playwright/test";

/**
 * Runs the local acceptance spec against an **already-running** app
 * (no webServer). Point it at the running instance with DRW_BASE_URL.
 *
 *   $env:DRW_BASE_URL = "http://localhost:3847"
 *   pnpm --filter @drw/web exec playwright test --config playwright.local.config.ts
 */
const baseURL = process.env.DRW_BASE_URL ?? "http://localhost:3847";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /(local-acceptance|accessibility)\.spec\.ts/,
  timeout: 300_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
