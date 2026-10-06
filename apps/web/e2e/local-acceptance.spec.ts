import { expect, test, type Page } from "@playwright/test";

/**
 * Live acceptance walkthrough against an already-running DRW instance.
 *
 * This drives the real UI in Chromium and exercises the full researcher
 * workflow, including the optional planner. It runs against the persistent
 * workspace, so it also verifies persistence across a page reload.
 *
 * Run with playwright.local.config.ts (see the header there).
 */
test.describe.configure({ mode: "serial" });

function watchForErrors(page: Page): { consoleErrors: string[]; failedRequests: string[] } {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  page.on("response", (response) => {
    if (response.status() >= 500) failedRequests.push(`${response.status()} ${response.url()}`);
  });
  return { consoleErrors, failedRequests };
}

async function openSample(page: Page): Promise<void> {
  await page.getByTestId("start-sample").click();
  await expect(page.getByRole("cell", { name: "alpha", exact: true })).toBeVisible();
}

async function validate(page: Page, expected: RegExp): Promise<void> {
  await page.getByTestId("validate-button").click();
  await expect(page.getByTestId("validation-verdict")).toHaveText(expected);
}

test.describe("live local acceptance", () => {
  test("full researcher workflow on the running application", async ({ page }) => {
    const { consoleErrors, failedRequests } = watchForErrors(page);

    // 1-2. Open the app; inspect projects and registered models.
    await page.goto("/?mode=manual");
    await expect(page.getByText("Researcher workspace")).toBeVisible();
    await expect(page.getByTestId("status-value")).toHaveText(/^idle$/);
    await expect(page.getByText(/registered model\(s\)/)).toBeVisible();
    await expect(page.getByTestId("project-select")).toBeVisible();

    // 3-5. Select the sample project/model and configure baseline + intervention.
    await openSample(page);
    await page.getByLabel(/^alpha \(/).fill("1.1");
    await page.getByLabel("value", { exact: true }).fill("1.21");

    // The active project is shown in the workspace context line.
    await expect(page.getByTestId("workspace-context")).toContainText("Sample: predator-prey");

    await page.screenshot({ path: "test-results/drw-sample-loaded.png", fullPage: true });

    // 6. Validate; then reject an invalid configuration and restore.
    await validate(page, /^valid$/);
    await expect(page.getByTestId("estimate-runs")).toHaveText("2");
    await page.getByLabel(/^alpha \(/).fill("999");
    await validate(page, /^invalid$/);
    await expect(page.getByTestId("run-button")).toBeDisabled();
    await page.getByLabel(/^alpha \(/).fill("1.1");
    await validate(page, /^valid$/);

    // 7-9. Execute and observe status/progress.
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^succeeded$/, { timeout: 150_000 });
    await expect(page.getByTestId("status-banner")).toContainText(/comparison\(s\) from 2 run\(s\)/);

    // 10-11. Differential metric matches the Python core's value for this spec.
    await page.getByRole("tab", { name: "Metrics" }).click();
    const metricsPanel = page.getByTestId("metrics-panel");
    await expect(metricsPanel.getByText("5.66464").first()).toBeVisible();
    await expect(metricsPanel.getByText("valid_points").first()).toBeVisible();

    // 11b. Result tabs are keyboard operable.
    const plotsTab = page.getByRole("tab", { name: "Plots" });
    await plotsTab.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("img", { name: /reference, variant and delta/i })).toBeVisible();

    // 12. Sensitivity ranking: cross-check the ordering the core computed.
    await page.getByRole("tab", { name: "Sensitivity" }).click();
    const table = page.getByTestId("sensitivity-table");
    await expect(table).toBeVisible({ timeout: 120_000 });
    const alphaDelta = Number(
      (await table.locator("tr", { hasText: /^alpha/ }).locator("td").nth(3).textContent()) ?? "NaN",
    );
    const betaDelta = Number(
      (await table.locator("tr", { hasText: /^beta/ }).locator("td").nth(3).textContent()) ?? "NaN",
    );
    expect(alphaDelta).toBeGreaterThan(0);
    expect(betaDelta).toBeGreaterThan(alphaDelta);

    // 13. Planner: propose, review, apply, validate, execute (no bypass).
    await page.getByTestId("planner-question").fill(
      "How does the prey peak change if alpha increases by 10%?",
    );
    await page.getByTestId("planner-propose").click();
    await expect(page.getByTestId("planner-proposal")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("planner-validation")).toContainText(/passes validation/i);
    await expect(page.getByTestId("planner-assumptions")).toBeVisible();
    await page.getByTestId("planner-apply").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^idle$/);
    await validate(page, /^valid$/);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^succeeded$/, { timeout: 150_000 });

    await page.screenshot({ path: "test-results/drw-results.png", fullPage: true });

    // 14. Evidence export.
    await page.getByRole("tab", { name: "Reproducibility" }).click();
    await expect(page.getByTestId("spec-hash")).toHaveText(/^[0-9a-f]{64}$/);
    await page.getByTestId("export-button").click();
    await expect(page.getByTestId("export-message")).toContainText(/wrote .*evidence\.zip/, {
      timeout: 60_000,
    });

    // 14b. Refresh: persisted experiments are still listed and reopen unchanged.
    await page.reload();
    const list = page.getByTestId("experiments-list");
    await expect(list.getByRole("button").first()).toBeVisible({ timeout: 60_000 });
    await list.getByRole("button").first().click();
    await expect(page.getByTestId("reopened-note")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("spec-preview")).toContainText('"alpha": 1.1');

    // 16. Timeout path is enforced and reported.
    await page.getByLabel(/Execution timeout/).fill("0.001");
    await validate(page, /^valid$/);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-value")).toHaveText(/^timed_out$/, { timeout: 150_000 });

    // 17. No console errors and no 5xx responses during the whole walkthrough.
    expect(failedRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
