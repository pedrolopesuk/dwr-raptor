import { expect, test } from "@playwright/test";

/**
 * Browser end-to-end: the production app in Chromium, executing the real Python
 * core through the JSON bridge.
 *
 * Cancellation is intentionally *not* browser-tested here: there is no
 * first-party long-running model to cancel deterministically. Cancellation is
 * covered by `tests/unit/test_isolation.py` (process kill) and the component test
 * `src/components/Workspace.test.tsx` (UI state). See the completion report.
 */
test.describe.configure({ mode: "serial" });

test.describe("researcher workflow in a browser", () => {
  test("open, configure, reject, run, inspect, reload, export and time out", async ({ page }) => {
    // 1. Open the workspace.
    await page.goto("/");
    await expect(page.getByText("Researcher workspace")).toBeVisible();
    await expect(page.getByTestId("status-value")).toHaveText(/^idle$/);

    // 2. Load the sample model.
    await page.getByTestId("start-sample").click();
    await expect(page.getByRole("cell", { name: "alpha", exact: true })).toBeVisible();
    await expect(page.getByTestId("project-select")).toBeVisible();

    // 3. Configure a baseline and an intervention.
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

    // 5. Run a valid experiment.
    await alpha.fill("1.1");
    await page.getByTestId("validate-button").click();
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^valid$/);
    await expect(page.getByTestId("run-button")).toBeEnabled();
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^succeeded$/, { timeout: 150_000 });

    // 5b. Measured progress is reported (the job journal reports completed runs).
    await expect(page.getByTestId("status-banner")).toContainText(/run/i);

    // 6. Inspect plots and differential metrics.
    await page.getByRole("tab", { name: "Plots" }).click();
    await expect(page.getByRole("img", { name: /reference, variant and delta/i })).toBeVisible();

    await page.getByRole("tab", { name: "Metrics" }).click();
    await expect(page.getByText("max_abs_delta").first()).toBeVisible();
    await expect(page.getByText("valid_points").first()).toBeVisible();

    await page.getByRole("tab", { name: "Sensitivity" }).click();
    await expect(page.getByTestId("sensitivity-table")).toBeVisible({ timeout: 120_000 });

    // 7. Export the evidence package.
    await page.getByRole("tab", { name: "Reproducibility" }).click();
    await expect(page.getByTestId("spec-hash")).toHaveText(/^[0-9a-f]{64}$/);
    await page.getByTestId("export-button").click();
    await expect(page.getByTestId("export-message")).toContainText(/wrote .*evidence\.zip/, {
      timeout: 60_000,
    });

    // 8. Reload the saved experiment and verify the configuration is unchanged.
    await page.getByTestId("experiments-list").getByRole("button").first().click();
    await expect(page.getByTestId("reopened-note")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("spec-preview")).toContainText('"alpha": 1.1');

    // 9. Timeout path: a 1 ms budget is enforced by the isolated runner.
    await page.getByLabel(/Execution timeout/).fill("0.001");
    await page.getByTestId("validate-button").click();
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^valid$/);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^timed_out$/, { timeout: 150_000 });
  });
});
