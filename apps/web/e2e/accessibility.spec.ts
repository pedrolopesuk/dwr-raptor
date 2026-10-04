import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Automated accessibility checks against a running DRW instance.
 *
 * Uses axe-core (bundled locally, no network) for serious/critical violations
 * and exercises keyboard access to the primary controls. This is not a screen
 * reader test and does not replace manual review - see the final report.
 */
test.describe.configure({ mode: "serial" });

function blocking(violations: { id: string; impact?: string | null; help: string }[]) {
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test.describe("accessibility and keyboard", () => {
  test("primary screens have no serious or critical axe violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Researcher workspace")).toBeVisible();

    const start = await new AxeBuilder({ page }).analyze();
    expect(
      blocking(start.violations).map((v) => `${v.id}: ${v.help}`),
      JSON.stringify(blocking(start.violations), null, 2),
    ).toEqual([]);

    // Dense screen: forms, tables, tabs.
    await page.getByTestId("start-sample").click();
    await expect(page.getByRole("cell", { name: "alpha", exact: true })).toBeVisible();

    const loaded = await new AxeBuilder({ page }).analyze();
    expect(
      blocking(loaded.violations).map((v) => `${v.id}: ${v.help}`),
      JSON.stringify(blocking(loaded.violations), null, 2),
    ).toEqual([]);
  });

  test("dark theme has no serious or critical axe violations", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Switch to dark theme/i }).click();
    await expect(page.getByRole("button", { name: /Switch to light theme/i })).toBeVisible();
    await page.getByTestId("start-sample").click();
    await expect(page.getByRole("cell", { name: "alpha", exact: true })).toBeVisible();

    const dark = await new AxeBuilder({ page }).analyze();
    expect(
      blocking(dark.violations).map((v) => `${v.id}: ${v.help}`),
      JSON.stringify(blocking(dark.violations), null, 2),
    ).toEqual([]);
  });

  test("keyboard access to primary navigation and experiment controls", async ({ page }) => {
    await page.goto("/");

    // The skip link is the first tab stop and targets the main region.
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toHaveAttribute("href", "#main-content");

    // The sample action is operable with the keyboard alone.
    await page.getByTestId("start-sample").focus();
    await expect(page.getByTestId("start-sample")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("cell", { name: "alpha", exact: true })).toBeVisible();

    // Project selector and the baseline field are focusable and labelled.
    const select = page.getByTestId("project-select");
    await select.focus();
    await expect(select).toBeFocused();

    const alpha = page.getByLabel(/^alpha \(/);
    await alpha.focus();
    await expect(alpha).toBeFocused();
    await page.keyboard.type("1.2");
    await expect(alpha).toHaveValue(/1\.2/);

    // Validation is reachable and activatable by keyboard.
    await page.getByTestId("validate-button").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("validation-verdict")).toHaveText(/^(valid|invalid)$/);
  });
});
