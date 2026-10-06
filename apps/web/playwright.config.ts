import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Browser-level end-to-end tests against the **production** Next.js build.
 *
 * `pnpm e2e` builds the app, then Playwright starts `next start` and drives a real
 * Chromium. Each run gets a throwaway workspace so saved experiments do not leak
 * between runs. The Python core must be installed (the route handlers spawn
 * `python -m drw.api`).
 */

const PORT = 3111;
const WORKSPACE = process.env.DRW_WORKSPACE ?? mkdtempSync(path.join(tmpdir(), "drw-pw-"));
// Share the isolated workspace with worker processes so tests can seed files
// (e.g. a CSV in dataset-sources/) that the server will read.
process.env.DRW_WORKSPACE = WORKSPACE;

export default defineConfig({
  testDir: "./e2e",
  // The local acceptance spec runs against an already-running app, not this one.
  testIgnore: /local-acceptance\.spec\.ts/,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `next start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      DRW_WORKSPACE: WORKSPACE,
    },
  },
});
