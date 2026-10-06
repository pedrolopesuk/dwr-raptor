import { expect, test, type Page } from "@playwright/test";

import { openAnalysis, runStoredSample } from "./helpers";

/**
 * Browser coverage for the parameter-identifiability panel.
 *
 * Drives the production app in Chromium against the real Python core. The
 * Playwright config supplies an isolated temporary workspace (`DRW_WORKSPACE`),
 * so nothing is written outside it. The cost estimate and the cap come from the
 * backend `capabilities` payload (no duplicated UI constants).
 */
test.describe.configure({ mode: "serial" });

/** Open the sample model, run it (storing it), and wait for the panel. */
async function openStoredSample(page: Page): Promise<void> {
  await runStoredSample(page);
  await openAnalysis(page, "Identifiability");
  await expect(page.getByTestId("ident-panel")).toBeVisible();
}

test.describe("parameter identifiability panel in a browser", () => {
  test("shows the backend cost estimate and the disclosed feature set", async ({ page }) => {
    await openStoredSample(page);
    const cost = page.getByTestId("ident-cost");
    await expect(cost).toContainText(/Estimated model evaluations:\s*13/);
    await expect(cost).toContainText(/d = 6/);
    await expect(cost).toContainText(/Maximum 4096 evaluations/);
    await expect(page.getByTestId("ident-features")).toContainText("argmax_t");
  });

  test("an explicit parameter selection updates the estimate", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("ident-factors").fill("beta, predator0");
    await expect(page.getByTestId("ident-cost")).toContainText(/Estimated model evaluations:\s*5/);
    await expect(page.getByTestId("ident-cost")).toContainText(/d = 2/);
  });

  test("a real study reports a poorly distinguishable direction", async ({ page }) => {
    await openStoredSample(page);
    await page.getByTestId("ident-factors").fill("beta, predator0");
    await page.getByTestId("ident-outputs").fill("prey");
    await page.getByTestId("ident-run").click();
    await expect(page.getByTestId("ident-verdict")).toContainText(/rank deficient/i, {
      timeout: 150_000,
    });
    await expect(page.getByTestId("ident-directions")).toContainText(/beta and predator0/i);
    await expect(page.getByTestId("ident-caveat")).toContainText(/local/i);
  });
});
