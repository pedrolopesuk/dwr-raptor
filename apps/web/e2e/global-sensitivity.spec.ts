import { expect, test, type Page } from "@playwright/test";

import { openAnalysis, runStoredSample } from "./helpers";

/**
 * Browser coverage for the global-sensitivity (Sobol) panel.
 *
 * Drives the production app in Chromium against the real Python core. The
 * Playwright config supplies an isolated temporary workspace (`DRW_WORKSPACE`),
 * so nothing is written outside it. The evaluation estimate and the cap come from
 * the backend `capabilities` payload (no duplicated UI constants).
 */
test.describe.configure({ mode: "serial" });

/** Open the sample model, run it (storing it), and wait for the Sobol panel. */
async function openStoredSample(page: Page): Promise<void> {
  await runStoredSample(page);
  await openAnalysis(page, "Sensitivity");
  await expect(page.getByTestId("sobol-panel")).toBeVisible();
}

test.describe("global sensitivity panel in a browser", () => {
  test("shows the backend default evaluation estimate", async ({ page }) => {
    await openStoredSample(page);
    const cost = page.getByTestId("sobol-cost");
    await expect(cost).toContainText("Default N = 32");
    await expect(cost).toContainText("Maximum 4096 evaluations");
    // predator-prey exposes 6 bounded numeric parameters by default: 32 * (6 + 2) = 256.
    await expect(cost).toContainText(/Estimated model evaluations:\s*256/);
    await expect(cost).toContainText(/d = 6/);
  });

  test("explicit factor selection updates the estimate", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("sobol-factors").fill("alpha, beta");
    await expect(page.getByTestId("sobol-cost")).toContainText(
      /Estimated model evaluations:\s*128/,
    );
    await expect(page.getByTestId("sobol-cost")).toContainText(/d = 2/);
  });

  test("changing the sample count updates the estimate", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("sobol-factors").fill("alpha, beta");
    await page.getByTestId("sobol-n").fill("64");
    await expect(page.getByTestId("sobol-cost")).toContainText(
      /Estimated model evaluations:\s*256/,
    );
  });

  test("a study exceeding the cap is explained and cannot be submitted", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("sobol-factors").fill("alpha, beta");
    await page.getByTestId("sobol-n").fill("2048");
    const cap = page.getByTestId("sobol-cap");
    await expect(cap).toContainText(/8192/);
    await expect(cap).toContainText(/4096/);
    await expect(page.getByTestId("sobol-run")).toBeDisabled();
  });

  test("missing capability metadata does not fabricate an estimate", async ({ page }) => {
    await page.route(/\/api\/models\/[^/]+\/capabilities$/, (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          ok: false,
          error: { code: "internal_error", message: "capabilities unavailable", diagnostics: [] },
        }),
      }),
    );
    await openStoredSample(page);
    const cost = page.getByTestId("sobol-cost");
    await expect(cost).toContainText(/unavailable/i);
    await expect(cost).not.toContainText(/Estimated model evaluations:/);
    await expect(page.getByTestId("sobol-run")).toBeEnabled();
  });

  test("a valid study runs and reports estimates", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("sobol-factors").fill("alpha, beta");
    await page.getByTestId("sobol-n").fill("4");
    await page.getByTestId("sobol-run").click();
    await expect(page.getByTestId("sobol-verdict")).toContainText(/estimated/i, {
      timeout: 150_000,
    });
    await expect(page.getByTestId("sobol-table")).toBeVisible();
  });
});
