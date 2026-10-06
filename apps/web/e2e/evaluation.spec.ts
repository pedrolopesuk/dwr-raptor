import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { investigationNav, openAnalysis, runStoredSample } from "./helpers";

/**
 * Browser coverage for observation <-> model evaluation (M12A).
 *
 * Runs the sample experiment, imports a scalar observation dataset, then
 * evaluates the stored baseline against it. Read-only and execution-free: the
 * panel never fits or infers. The Playwright config shares an isolated temporary
 * workspace (`DRW_WORKSPACE`) with worker processes.
 */

const WORKSPACE = process.env.DRW_WORKSPACE ?? "";
const OBSERVATIONS = ["peak_prey", "13.0", "14.0", "15.0", ""].join("\n");

test.beforeAll(() => {
  if (!WORKSPACE) throw new Error("DRW_WORKSPACE is not set for the evaluation E2E run");
  const dir = path.join(WORKSPACE, "dataset-sources");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "peak_obs.csv"), OBSERVATIONS, "utf-8");
});

test.describe.configure({ mode: "serial" });

async function openStoredSample(page: Page): Promise<void> {
  await runStoredSample(page);
}

test.describe("observation <-> model evaluation in a browser", () => {
  test("evaluates a stored run against an imported dataset", async ({ page }) => {
    await openStoredSample(page);

    // Import the scalar observation dataset (one measurement column).
    await investigationNav(page, "Data").click();
    await page.getByTestId("dataset-source").selectOption("peak_obs.csv");
    await page.getByTestId("dataset-inspect").click();
    await expect(page.getByTestId("dataset-preview")).toBeVisible();
    await page.locator("#dataset-unit-peak_prey").fill("count");
    await page.getByTestId("dataset-dsname").fill("observed peaks");
    await page.getByTestId("dataset-import").click();
    await expect(page.getByTestId("dataset-result")).toContainText(/imported/i);

    // Evaluate the stored baseline against it.
    await openAnalysis(page, "Evaluation");
    const datasetOption = page.getByTestId("eval-dataset").locator("option", { hasText: "observed peaks" }).first();
    await expect(datasetOption).toHaveCount(1);
    const datasetValue = await datasetOption.getAttribute("value");
    await page.getByTestId("eval-dataset").selectOption(datasetValue ?? "");
    const mapping = page.getByTestId("eval-mapping");
    const parsed = JSON.parse(await mapping.inputValue());
    parsed.pairs[0].observation = "peak_prey";
    parsed.pairs[0].output = "peak_prey";
    await mapping.fill(JSON.stringify(parsed));

    await page.getByTestId("eval-run-button").click();
    await expect(page.getByTestId("eval-verdict")).toContainText(/evaluated/i, { timeout: 60_000 });
    await expect(page.getByTestId("eval-metrics-table")).toContainText("peak_prey");
    await expect(page.getByTestId("eval-provenance")).toContainText(/dataset/);
  });
});
