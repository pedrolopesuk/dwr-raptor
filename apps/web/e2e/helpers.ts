import { expect, type Page } from "@playwright/test";

export const PROJECT = "default";
export const INVESTIGATIONS = `/projects/${PROJECT}/investigations`;

export function investigationNav(page: Page, name: string) {
  return page
    .getByRole("navigation", { name: "Investigation" })
    .getByRole("link", { name, exact: true });
}

export function projectNav(page: Page, name: string) {
  return page.getByRole("navigation", { name: "Project" }).getByRole("link", { name, exact: true });
}

/** Opens the sample as an unsaved draft investigation (nothing has run). */
export async function startSampleDraft(page: Page): Promise<void> {
  await page.goto(`${INVESTIGATIONS}/draft/overview`);
  await expect(page.getByTestId("no-draft")).toBeVisible();
  await page.getByTestId("open-sample").click();
  await expect(page.getByTestId("investigation-question")).toBeVisible();
}

/** From a draft: open the Configuration page. */
export async function openConfiguration(page: Page): Promise<void> {
  await investigationNav(page, "Experiments").click();
  await page.getByRole("link", { name: "Configuration", exact: true }).click();
  await expect(page.getByTestId("experiment-configure")).toBeVisible();
}

/** Validates and runs the configuration; resolves once the investigation is stored. */
export async function validateAndRun(page: Page): Promise<void> {
  await page.getByTestId("validate-button").click();
  await expect(page.getByTestId("validation-verdict")).toHaveText(/^valid$/);
  await page.getByTestId("run-button").click();
  await page.waitForURL(/investigations\/exp-[0-9a-f]+\/experiments/, { timeout: 150_000 });
  await expect(page.getByTestId("status-value")).toHaveText(/^succeeded$/, { timeout: 150_000 });
}

/** Sample draft -> configured -> run -> stored investigation (on its Experiments page). */
export async function runStoredSample(page: Page): Promise<void> {
  await startSampleDraft(page);
  await openConfiguration(page);
  await validateAndRun(page);
}

/** Opens a focused analysis page of the stored investigation, e.g. "Sensitivity". */
export async function openAnalysis(page: Page, name: string): Promise<void> {
  await investigationNav(page, "Analysis").click();
  await page.getByRole("link", { name: new RegExp(`^${name}`) }).click();
}
