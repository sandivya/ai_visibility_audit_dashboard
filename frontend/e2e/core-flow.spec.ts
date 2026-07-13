import { expect, test } from "@playwright/test";
import { expectNoSeriousAccessibilityViolations } from "./accessibility";
import { attachReviewScreenshot } from "./review-artifacts";
import { signInAsAlice } from "./session";

test.describe.configure({ mode: "serial" });

async function createProject(
  page: Parameters<typeof signInAsAlice>[0],
  input: { name: string; domain: string; competitors?: string },
) {
  await page.getByRole("button", { name: /new project/i }).click();
  const dialog = page.getByRole("dialog", { name: /create a project/i });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Project name").fill(input.name);
  await dialog.getByLabel("Domain").fill(input.domain);
  if (input.competitors) {
    await dialog.getByLabel(/Competitors/).fill(input.competitors);
  }
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/prj_[a-z0-9]+$/);
  await expect(page.getByRole("heading", { name: input.name })).toBeVisible();
}

test("an evaluator can validate, create, and open a project", async ({ page }, testInfo) => {
  await signInAsAlice(page);
  await page.getByRole("button", { name: /new project/i }).click();
  const dialog = page.getByRole("dialog", { name: /create a project/i });
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(dialog.getByText("Enter a project name.")).toBeVisible();
  await expect(dialog.getByText(/Enter a valid domain/)).toBeVisible();

  const suffix = `${Date.now()}-${test.info().retry}`;
  await dialog.getByLabel("Project name").fill("E2E Visibility Lab");
  await dialog.getByLabel("Domain").fill(`visibility-${suffix}.example.com`);
  await dialog.getByLabel(/Competitors/).fill("rival-one.com, rival-two.com");
  await dialog.getByRole("button", { name: "Create project" }).click();

  await expect(page).toHaveURL(/\/projects\/prj_[a-z0-9]+$/);
  await expect(page.getByRole("heading", { name: "E2E Visibility Lab" })).toBeVisible();
  await expect(page.getByText("rival-one.com", { exact: true })).toBeVisible();
  await expect(page.getByText("rival-two.com", { exact: true })).toBeVisible();
  await expectNoSeriousAccessibilityViolations(page);
  await attachReviewScreenshot(page, testInfo, "project-detail");
});

test("a completed audit exposes evidence, insights, and recommendation workflow", async ({
  page,
}, testInfo) => {
  await signInAsAlice(page);
  await page
    .getByRole("link", { name: /Acme Skincare/ })
    .first()
    .click();
  await page.getByRole("button", { name: /run new audit/i }).click();

  await expect(page).toHaveURL(/\/audits\/aud_[a-z0-9]+$/);
  await expect(page.getByRole("heading", { name: "Audit detail" })).toBeVisible();
  await expect(page.getByLabel(/Status: (queued|processing|completed)/i)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Brand missing from a high-intent prompt", exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await expect(page.getByText(/mention rate/i)).toBeVisible();
  await expect(page.getByText(/glowco\.com/i)).toBeVisible();

  const recommendationStatus = page.getByLabel(/Status for Publish comparison-led content/i);
  await recommendationStatus.selectOption("completed");
  await expect(page.getByText("Recommendation updated")).toBeVisible();
  await expectNoSeriousAccessibilityViolations(page);
  await attachReviewScreenshot(page, testInfo, "completed-audit");
});

test("a failed audit offers a recovery action", async ({ page }) => {
  await signInAsAlice(page);
  const suffix = `${Date.now()}-${test.info().retry}`;
  await createProject(page, {
    name: "E2E Failure Recovery",
    domain: `fail-${suffix}.example.com`,
  });
  await page.getByRole("button", { name: /run new audit/i }).click();

  await expect(page.getByText(/simulated provider could not analyze/i)).toBeVisible({
    timeout: 25_000,
  });
  await expect(page.getByRole("button", { name: /retry audit/i })).toBeVisible();
});

test("switching workspaces visibly preserves tenant isolation", async ({ page }) => {
  await signInAsAlice(page);
  await page.getByLabel("Viewing workspace").selectOption("usr_bob");
  await expect(page.getByRole("heading", { name: "Beta Finance" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Acme Skincare" })).toHaveCount(0);
});
