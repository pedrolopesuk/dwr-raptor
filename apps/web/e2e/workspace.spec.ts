import { expect, test } from "@playwright/test";

import {
  investigationNav,
  openConfiguration,
  projectNav,
  startSampleDraft,
} from "./helpers";

/**
 * Browser end-to-end: the production app in Chromium, executing the real Python
 * core through the JSON bridge, navigating the real nested routes.
 *
 * Cancellation is intentionally *not* browser-tested here: there is no
 * first-party long-running model to cancel deterministically. Cancellation is
 * covered by `tests/unit/test_isolation.py` (process kill) and the routed
 * component test `src/views/app.test.tsx` (UI state). See the completion report.
 */
test.describe.configure({ mode: "serial" });

test.describe("researcher workflow in a browser", () => {
  test("the root opens the first project overview with SI first", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/projects\/[^/]+$/);
    await expect(page.getByRole("heading", { name: "What are you investigating?" })).toBeVisible();
    await expect(page.getByTestId("mode-si")).toHaveAttribute("aria-selected", "true");
    for (const name of ["Overview", "Investigations", "Data", "Models", "Experiments", "Evidence"]) {
      await expect(projectNav(page, name)).toBeVisible();
    }
  });

  test("start, configure, reject, run, inspect, trace, reload, export and time out", async ({ page }) => {
    // 1. Start the sample as a draft investigation.
    await startSampleDraft(page);
    await expect(page.getByTestId("investigation-conclusion")).toHaveText("Not established.");
    await expect(page).toHaveURL(/investigations\/draft\/overview$/);

    // 2. The model has its own page.
    await investigationNav(page, "Model").click();
    await page.getByRole("tab", { name: "Parameters", exact: true }).click();
    await expect(page.getByRole("cell", { name: /alpha/ }).first()).toBeVisible();

    // 3. Configure a baseline and an intervention.
    await openConfiguration(page);
    await expect(page.getByTestId("status-value")).toHaveText(/^idle$/);
    const alpha = page.getByLabel(/^alpha \(/);
    await alpha.fill("1.2");
    await page.getByLabel("value", { exact: true }).fill("1.35");
    await expect(page.getByTestId("spec-preview")).toContainText('"alpha": 1.2');

    // 4. Reject an invalid configuration.
    await alpha.fill("999");
    await page.getByTestId("validate-button").click();
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^invalid$/);
    await expect(page.getByText(/baseline_out_of_bounds|factor_out_of_bounds/)).toBeVisible();
    await expect(page.getByTestId("run-button")).toBeDisabled();

    // 5. Run a valid experiment; the investigation is stored under its experiment id.
    await alpha.fill("1.1");
    await page.getByTestId("validate-button").click();
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^valid$/);
    await expect(page.getByTestId("run-button")).toBeEnabled();
    await page.getByTestId("run-button").click();
    await page.waitForURL(/investigations\/exp-[0-9a-f]+\/experiments$/, { timeout: 150_000 });
    await expect(page.getByTestId("status-value")).toHaveText(/^succeeded$/, { timeout: 150_000 });
    await expect(page.getByTestId("runs-list")).toBeVisible();
    const storedUrl = page.url();

    // 6. Inspect plots, differential metrics and sensitivity.
    await page.getByRole("link", { name: "Results", exact: true }).click();
    await page.getByRole("tab", { name: "Plots" }).click();
    await expect(page.getByRole("img", { name: /reference, variant and delta/i })).toBeVisible();
    await page.getByRole("tab", { name: "Metrics" }).click();
    await expect(page.getByText("max_abs_delta").first()).toBeVisible();
    await expect(page.getByText("valid_points").first()).toBeVisible();
    await page.getByRole("tab", { name: "Sensitivity" }).click();
    await expect(page.getByTestId("sensitivity-table")).toBeVisible({ timeout: 120_000 });

    // 7. Evidence: the traceable chain, reproduction, and the evidence export.
    await investigationNav(page, "Evidence").click();
    await expect(page.getByTestId("evidence-chain")).toBeVisible();
    await expect(page.getByTestId("spec-hash-full")).toHaveText(/^[0-9a-f]{64}$/);
    await expect(page.getByTestId("model-hash")).toHaveText(/^[0-9a-f]{64}$/);

    await page.getByTestId("reproduce-rtol").fill("1e-9");
    await page.getByTestId("reproduce-atol").fill("1e-12");
    await page.getByTestId("reproduce-button").click();
    await expect(page.getByTestId("reproduce-verdict")).toHaveText(
      /identical|equivalent within tolerance/i,
      { timeout: 150_000 },
    );
    await expect(page.getByTestId("reproduce-provenance")).toContainText("yes");

    // 7b. The reproduce controls remain usable at a supported narrow viewport.
    await page.setViewportSize({ width: 900, height: 900 });
    await expect(page.getByTestId("reproduce-rtol")).toBeVisible();
    await expect(page.getByTestId("reproduce-atol")).toBeVisible();
    await expect(page.getByTestId("reproduce-button")).toBeVisible();
    const panelOverflow = await page
      .getByTestId("reproduce-panel")
      .evaluate((element) => element.scrollWidth - element.clientWidth);
    expect(panelOverflow).toBeLessThanOrEqual(1);
    await page.setViewportSize({ width: 1280, height: 720 });

    await page.getByTestId("export-button").click();
    await expect(page.getByTestId("export-message")).toContainText(/wrote .*evidence\.zip/, {
      timeout: 60_000,
    });

    // 8. Reload the stored investigation straight from its URL: configuration unchanged.
    await page.goto(storedUrl.replace(/experiments$/, "experiments/configure"));
    await expect(page.getByTestId("reopened-note")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("spec-preview")).toContainText('"alpha": 1.1');

    // 8b. It is listed under Investigations and opens from there.
    await projectNav(page, "Investigations").click();
    await expect(page.getByTestId("investigations-list")).toBeVisible();
    await page.getByTestId("investigations-list").getByRole("link").first().click();
    await expect(page).toHaveURL(/investigations\/exp-[0-9a-f]+\/overview$/);

    // 9. Timeout path: a 1 ms budget is enforced by the isolated runner.
    await page.goto(storedUrl.replace(/experiments$/, "experiments/configure"));
    await page.getByLabel(/Execution timeout/).fill("0.001");
    await page.getByTestId("validate-button").click();
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^valid$/);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^timed_out$/, { timeout: 150_000 });
  });

  test("validation is shown honestly as not implemented", async ({ page }) => {
    await startSampleDraft(page);
    await investigationNav(page, "Validation").click();
    await expect(page.getByTestId("validation-unavailable")).toContainText(
      "Not implemented in this version",
    );
  });
});
