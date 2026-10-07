import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { investigationNav, openAnalysis, runStoredSample } from "./helpers";

/**
 * Browser coverage for validation (M12C).
 *
 * Runs the sample experiment, imports two scalar datasets (one to calibrate on,
 * one held out), persists a calibration, then validates the FROZEN calibrated
 * model against the independent dataset. Read-only w.r.t. the experiment: the
 * panel drives the existing Runner + M12A through the bridge, and never refits.
 */

const WORKSPACE = process.env.DRW_WORKSPACE ?? "";
// Distinct column names so the two inspections do not share a unit field.
const CALIBRATION_CSV = ["peak_calib", "13.0", "14.0", "15.0", ""].join("\n");
const VALIDATION_CSV = ["held_peak", "13.5", "14.2", "15.1", ""].join("\n");

test.beforeAll(() => {
  if (!WORKSPACE) throw new Error("DRW_WORKSPACE is not set for the validation E2E run");
  const dir = path.join(WORKSPACE, "dataset-sources");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "cal_peaks.csv"), CALIBRATION_CSV, "utf-8");
  writeFileSync(path.join(dir, "val_peaks.csv"), VALIDATION_CSV, "utf-8");
});

test.describe.configure({ mode: "serial" });

async function importDataset(
  page: Page,
  filename: string,
  name: string,
  column: string,
): Promise<void> {
  await investigationNav(page, "Data").click();
  await page.getByTestId("dataset-source").selectOption(filename);
  await page.getByTestId("dataset-inspect").click();
  // Wait for THIS column's field so a slower inspection cannot reset it afterwards.
  const unit = page.locator(`#dataset-unit-${column}`);
  await expect(unit).toBeVisible();
  await unit.fill("count");
  await page.getByTestId("dataset-dsname").fill(name);
  await page.getByTestId("dataset-import").click();
  await expect(page.getByTestId("dataset-result")).toContainText(/imported/i);
}

async function selectByText(page: Page, testId: string, text: RegExp | string): Promise<void> {
  const option = page.getByTestId(testId).locator("option", { hasText: text });
  await expect(option).toHaveCount(1);
  await page.getByTestId(testId).selectOption((await option.getAttribute("value")) ?? "");
}

test.describe("validation in a browser", () => {
  test("validates a frozen calibration against an independent dataset", async ({ page }) => {
    await runStoredSample(page);

    await importDataset(page, "cal_peaks.csv", "cal peaks", "peak_calib");
    await importDataset(page, "val_peaks.csv", "held out peaks", "held_peak");

    // Calibrate on the first dataset and persist the result.
    await openAnalysis(page, "Calibration");
    await selectByText(page, "calib-dataset", "cal peaks");
    await page.locator('label[for="calib-free-alpha"]').click();
    const calMapping = page.getByTestId("calib-mapping");
    const calParsed = JSON.parse(await calMapping.inputValue());
    calParsed.pairs[0].observation = "peak_calib";
    calParsed.pairs[0].output = "peak_prey";
    await calMapping.fill(JSON.stringify(calParsed));
    await page.getByTestId("calib-optimizer").selectOption("random_search");
    await page.getByTestId("calib-max-evals").fill("3");
    await page.getByTestId("calib-identifiability").selectOption("off");
    await page.getByTestId("calib-run").click();
    await expect(page.getByTestId("calib-stored")).toContainText(/cal-/, { timeout: 120_000 });
    // Select exactly the calibration we just created (other specs share the workspace).
    const storedText = await page.getByTestId("calib-stored").innerText();
    const calibrationId = storedText.match(/cal-[0-9a-f]+/)?.[0] ?? "";
    expect(calibrationId).not.toBe("");

    // Validate the frozen calibration against the held-out dataset.
    await investigationNav(page, "Validation").click();
    await page.getByTestId("val-calibration").selectOption(calibrationId);
    await selectByText(page, "val-dataset", "held out peaks");
    const valMapping = page.getByTestId("val-mapping");
    const valParsed = JSON.parse(await valMapping.inputValue());
    valParsed.pairs[0].observation = "held_peak";
    valParsed.pairs[0].output = "peak_prey";
    await valMapping.fill(JSON.stringify(valParsed));

    await page.getByTestId("val-run").click();
    // Assert on the per-dataset text so a failure surfaces its explicit code.
    await expect(page.getByTestId("val-dataset-0")).toContainText(/agreement evaluated/, {
      timeout: 150_000,
    });
    await expect(page.getByTestId("val-axes")).toContainText(/independence/);
    await expect(page.getByTestId("val-note")).toContainText(/frozen/i);
  });
});
