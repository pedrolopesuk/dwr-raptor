import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { investigationNav, openAnalysis, runStoredSample } from "./helpers";

/**
 * Browser coverage for calibration (M12B).
 *
 * Runs the sample experiment, imports a scalar observation dataset, then
 * calibrates one bounded parameter against it with the deterministic random-search
 * baseline (a small hard budget). Read-only w.r.t. the experiment: the panel drives
 * the existing Runner + M12A through the bridge. A point estimate only.
 */

const WORKSPACE = process.env.DRW_WORKSPACE ?? "";
const OBSERVATIONS = ["peak_prey", "13.0", "14.0", "15.0", ""].join("\n");

test.beforeAll(() => {
  if (!WORKSPACE) throw new Error("DRW_WORKSPACE is not set for the calibration E2E run");
  const dir = path.join(WORKSPACE, "dataset-sources");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "peak_obs.csv"), OBSERVATIONS, "utf-8");
});

test.describe.configure({ mode: "serial" });

async function openStoredSample(page: Page): Promise<void> {
  await runStoredSample(page);
}

test.describe("calibration in a browser", () => {
  test("calibrates a bounded parameter against an imported dataset", async ({ page }) => {
    await openStoredSample(page);

    // Import a scalar observation dataset (one measurement column).
    await investigationNav(page, "Data").click();
    await page.getByTestId("dataset-source").selectOption("peak_obs.csv");
    await page.getByTestId("dataset-inspect").click();
    await expect(page.getByTestId("dataset-preview")).toBeVisible();
    await page.locator("#dataset-unit-peak_prey").fill("count");
    await page.getByTestId("dataset-dsname").fill("observed peaks");
    await page.getByTestId("dataset-import").click();
    await expect(page.getByTestId("dataset-result")).toContainText(/imported/i);

    // Configure the calibration: dataset, one free parameter, mapping, small budget.
    await openAnalysis(page, "Calibration");
    const datasetOption = page.getByTestId("calib-dataset").locator("option", { hasText: "observed peaks" });
    await expect(datasetOption).toHaveCount(1);
    await page.getByTestId("calib-dataset").selectOption((await datasetOption.getAttribute("value")) ?? "");
    await page.getByTestId("calib-free-alpha").check();

    const mapping = page.getByTestId("calib-mapping");
    const parsed = JSON.parse(await mapping.inputValue());
    parsed.pairs[0].observation = "peak_prey";
    parsed.pairs[0].output = "peak_prey";
    await mapping.fill(JSON.stringify(parsed));

    await page.getByTestId("calib-optimizer").selectOption("random_search");
    await page.getByTestId("calib-max-evals").fill("3");
    await page.getByTestId("calib-identifiability").selectOption("off");

    await page.getByTestId("calib-run").click();
    await expect(page.getByTestId("calib-status")).toContainText(
      /budget_exhausted|converged|not_converged/,
      { timeout: 120_000 },
    );
    await expect(page.getByTestId("calib-best")).toContainText("alpha");
    await expect(page.getByTestId("calib-note")).toContainText(/point estimate/i);
  });
});
