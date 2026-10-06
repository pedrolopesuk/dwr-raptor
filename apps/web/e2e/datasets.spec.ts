import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

/**
 * Browser coverage for CSV dataset import (M11C).
 *
 * Drives the production app in Chromium against the real Python core. The
 * Playwright config shares an isolated temporary workspace (`DRW_WORKSPACE`) with
 * worker processes, so this spec can seed a CSV into `dataset-sources/` and the
 * bridge will read it. Nothing is written outside the temp workspace.
 */

const WORKSPACE = process.env.DRW_WORKSPACE ?? "";

const LIGHTCURVE = [
  "time,flux,flux_err",
  "2026-01-01T00:00:00Z,12.30,0.10",
  "2026-01-01T00:01:00Z,12.35,0.10",
  "2026-01-01T00:02:00Z,12.28,0.11",
  "",
].join("\n");

test.beforeAll(() => {
  if (!WORKSPACE) throw new Error("DRW_WORKSPACE is not set for the dataset E2E run");
  const dir = path.join(WORKSPACE, "dataset-sources");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "lightcurve.csv"), LIGHTCURVE, "utf-8");
});

test.describe.configure({ mode: "serial" });

test.describe("CSV dataset import in a browser", () => {
  test("inspects, configures and imports an immutable dataset", async ({ page }) => {
    await page.goto("/projects/default/data");
    await expect(page.getByTestId("dataset-panel")).toBeVisible();
    await expect(page.getByTestId("dataset-advisory")).toContainText(/advisory/i);

    await page.getByTestId("dataset-source").selectOption("lightcurve.csv");
    await page.getByTestId("dataset-inspect").click();

    // Detected structure is shown as a preview + per-column configuration.
    await expect(page.getByTestId("dataset-preview")).toBeVisible();
    await expect(page.getByTestId("dataset-role-time")).toHaveValue("coordinate");

    // Explicit unit + uncertainty assignment.
    await page.locator("#dataset-unit-flux").fill("Jy");
    await page.locator("#dataset-unit-flux_err").fill("Jy");
    await page.getByTestId("dataset-unc-flux").selectOption("std");
    await page.locator("#dataset-unccol-flux").fill("flux_err");
    await page.getByTestId("dataset-dsname").fill("lightcurve");

    // Validate (dry run) does not persist.
    await page.getByTestId("dataset-validate").click();
    await expect(page.getByTestId("dataset-result")).toContainText(/validated/i);

    // Import writes the immutable dataset.
    await page.getByTestId("dataset-import").click();
    await expect(page.getByTestId("dataset-result")).toContainText(/imported/i);

    // It appears in the dataset list.
    await expect(page.getByTestId("datasets-list")).toContainText("lightcurve");
    await expect(page.getByTestId("datasets-list")).toContainText("file");

    // Open the detail: variables, units, uncertainty and verification.
    await page.locator('[data-testid^="dataset-row-"]').first().click();
    await expect(page.getByTestId("dataset-detail")).toBeVisible();
    await expect(page.getByTestId("dataset-variables")).toContainText("Jy");
    await expect(page.getByTestId("dataset-verification")).toContainText("meta");

    // Verification is read-only and reports success.
    await page.getByTestId("dataset-verify").click();
    await expect(page.getByTestId("dataset-detail")).toContainText(/verified/i);
  });

  test("surfaces an invalid configuration", async ({ page }) => {
    await page.goto("/projects/default/data");
    await page.getByTestId("dataset-source").selectOption("lightcurve.csv");
    await page.getByTestId("dataset-inspect").click();
    await expect(page.getByTestId("dataset-preview")).toBeVisible();

    // Declare an uncertainty companion that does not exist -> import must fail.
    await page.getByTestId("dataset-unc-flux").selectOption("std");
    await page.locator("#dataset-unccol-flux").fill("does_not_exist");
    await page.getByTestId("dataset-import").click();

    await expect(page.getByTestId("dataset-error")).toBeVisible();
  });
});
