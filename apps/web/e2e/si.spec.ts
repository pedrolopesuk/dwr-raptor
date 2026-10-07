import { expect, test } from "@playwright/test";

/**
 * Browser end-to-end: SI turns a natural-language question into a structured,
 * inspectable plan, requires explicit approval for the step that creates an
 * artifact, runs it through the real Python core, and interprets the result.
 *
 * The rule-based SI planner is used (no LLM provider is configured), so the test
 * is deterministic. Steps are run in order; each step's run button is disabled
 * until the steps it depends on have executed.
 */
test.describe.configure({ mode: "serial" });

test("SI plans, requires approval, runs and interprets a real workflow", async ({ page }) => {
  await page.goto("/");
  await page.waitForURL(/\/projects\/[^/]+$/);

  // 1. Ask SI a scientific question from the project overview.
  await expect(page.getByTestId("si-input")).toBeVisible();
  await page
    .getByTestId("si-input")
    .fill("Design an experiment to see how alpha changes the prey peak.");
  await page.getByTestId("si-send").click();

  // 2. The question continues in the investigation's SI page as a structured plan.
  await page.waitForURL(/investigations\/draft\/si$/);
  const plan = page.getByTestId("si-plan");
  await expect(plan).toBeVisible();
  await expect(plan).toContainText("Proposed steps");
  // At least one step creates an artifact and is marked as requiring approval.
  await expect(plan.getByText("Requires approval").first()).toBeVisible();

  // 3. Run the steps in order. Read-only steps run without approval; the mutating
  //    step is approved by clicking "Approve & run". A step stays disabled until
  //    its dependencies have executed.
  for (let i = 0; i < 12; i += 1) {
    const enabled = page.locator('[data-testid^="si-run-step-"]:enabled');
    if ((await enabled.count()) === 0) break;
    const before = await page.locator('[data-testid^="si-run-step-"]').count();
    await enabled.first().click();
    await expect(page.locator('[data-testid^="si-run-step-"]')).toHaveCount(before - 1, {
      timeout: 150_000,
    });
  }

  // 4. The mutating step ran a real experiment, and SI interpreted the result with
  //    an explicit statement of what it does not establish.
  await expect(page.getByTestId("si-interpretation")).toBeVisible();
  await expect(page.getByTestId("si-interpretation")).toContainText("What it does not establish");
  await expect(plan).toContainText("Executed");
});
