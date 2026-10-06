import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import {
  INVESTIGATIONS,
  investigationNav,
  openConfiguration,
  projectNav,
  startSampleDraft,
  validateAndRun,
} from "./helpers";

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

async function expectNoBlocking(page: Page): Promise<void> {
  const scan = await new AxeBuilder({ page }).analyze();
  expect(
    blocking(scan.violations).map((v) => `${v.id}: ${v.help}`),
    JSON.stringify(blocking(scan.violations), null, 2),
  ).toEqual([]);
}

test.describe("accessibility and keyboard", () => {
  test("project and investigation pages have no serious or critical axe violations", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/projects\/[^/]+$/);
    await expect(page.getByRole("heading", { name: "What are you investigating?" })).toBeVisible();
    await expectNoBlocking(page);

    await projectNav(page, "Investigations").click();
    await expect(page.getByTestId("investigations-index")).toBeVisible();
    await expectNoBlocking(page);

    await projectNav(page, "Models").click();
    await expect(page.getByTestId("models-list")).toBeVisible();
    await expectNoBlocking(page);

    // Dense screens: overview with state table, model tabs, configuration form.
    await startSampleDraft(page);
    await expectNoBlocking(page);
    await investigationNav(page, "Model").click();
    await expect(page.getByTestId("investigation-model")).toBeVisible();
    await expectNoBlocking(page);
    await openConfiguration(page);
    await expectNoBlocking(page);
    await investigationNav(page, "Validation").click();
    await expectNoBlocking(page);
  });

  test("dark theme has no serious or critical axe violations", async ({ page }) => {
    await page.goto(`${INVESTIGATIONS}/draft/overview`);
    await page.getByRole("button", { name: /Switch to dark theme/i }).click();
    await expect(page.getByRole("button", { name: /Switch to light theme/i })).toBeVisible();
    await page.getByTestId("open-sample").click();
    await expect(page.getByTestId("investigation-question")).toBeVisible();
    await expectNoBlocking(page);
    await openConfiguration(page);
    await expectNoBlocking(page);
  });

  test("keyboard access to navigation and experiment controls", async ({ page }) => {
    await page.goto(`${INVESTIGATIONS}/draft/overview`);

    // The skip link is the first tab stop and targets the main region.
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toHaveAttribute("href", "#main-content");

    // Sidebar links are focusable and operable with the keyboard alone.
    const modelsLink = projectNav(page, "Models");
    await modelsLink.focus();
    await expect(modelsLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("models-list")).toBeVisible();

    // The sample action is operable with the keyboard alone.
    await page.goto(`${INVESTIGATIONS}/draft/overview`);
    await page.getByTestId("open-sample").focus();
    await expect(page.getByTestId("open-sample")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("investigation-question")).toBeVisible();

    // Investigation navigation is a labelled landmark with a current page.
    await expect(investigationNav(page, "Overview")).toHaveAttribute("aria-current", "page");

    await openConfiguration(page);
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

  test("evidence page has no serious/critical axe violations and reproduce controls are keyboard reachable", async ({
    page,
  }) => {
    await startSampleDraft(page);
    await openConfiguration(page);
    await validateAndRun(page);

    await investigationNav(page, "Evidence").click();
    await expect(page.getByTestId("evidence-chain")).toBeVisible();
    const rtol = page.getByTestId("reproduce-rtol");
    await rtol.focus();
    await expect(rtol).toBeFocused();
    await page.keyboard.type("1e-9");
    await expect(rtol).toHaveValue(/1e-9/);
    await expectNoBlocking(page);
  });
});
