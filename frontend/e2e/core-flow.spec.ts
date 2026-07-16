import { expect, test } from "@playwright/test";
import { expectNoSeriousAccessibilityViolations } from "./accessibility";
import { attachReviewScreenshot } from "./review-artifacts";
import { signInAsAlice } from "./session";

test.describe.configure({ mode: "serial" });

let completedAuditId = "";

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
  await dialog.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/prj_[a-z0-9]+$/);
  await expect(page.getByRole("heading", { name: input.name })).toBeVisible();
}

test("an evaluator can validate, create, and open a project", async ({ page }, testInfo) => {
  await signInAsAlice(page);
  await page.getByRole("button", { name: /new project/i }).click();
  const dialog = page.getByRole("dialog", { name: /create a project/i });
  await dialog.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(dialog.getByText("Enter a project name.")).toBeVisible();
  await expect(dialog.getByText(/Enter a valid domain/)).toBeVisible();

  const suffix = `${Date.now()}-${test.info().retry}`;
  await dialog.getByLabel("Project name").fill("E2E Visibility Lab");
  await dialog.getByLabel("Domain").fill(`visibility-${suffix}.example.com`);
  await dialog.getByLabel(/Competitors/).fill("rival-one.com, rival-two.com");
  await dialog.getByRole("button", { name: "Create project", exact: true }).click();

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
  await page.goto("/projects/prj_acme_demo");
  await expect(page.getByRole("heading", { name: "Acme Skincare" })).toBeVisible();
  await page.getByRole("button", { name: /run new audit/i }).click();

  await expect(page).toHaveURL(/\/audits\/aud_[a-z0-9]+$/);
  completedAuditId = new URL(page.url()).pathname.split("/").at(-1) ?? "";
  await expect(page.getByRole("heading", { name: "Audit detail" })).toBeVisible();
  await expect(page.getByLabel(/Status: (queued|processing|completed)/i)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Brand missing from a high-intent prompt", exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await expect(page.getByLabel(`Copy full audit ID ${completedAuditId}`)).toBeVisible();
  await expect(page.getByLabel(/Score: \d+ out of 100/)).toBeVisible();
  await expect(
    page.getByText("Pages analyzed").locator("..").getByText("2", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Prompts checked").locator("..").getByText("2", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/mention rate/i)).toBeVisible();
  await expect(page.getByText(/glowco\.com/i)).toBeVisible();
  for (const section of [
    "What is driving visibility",
    "Findings",
    "Recommendations",
    "Page evidence",
    "Prompt evidence",
    "Audit timeline",
  ]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible();
  }

  const recommendationStatus = page.getByLabel(/Status for Publish comparison-led content/i);
  await recommendationStatus.selectOption("in_progress");
  await expect(recommendationStatus).toHaveValue("in_progress");
  await recommendationStatus.selectOption("completed");
  await expect(recommendationStatus).toHaveValue("completed");
  await expect(page.getByText("Recommendation updated")).toBeVisible();

  await page.goto("/projects/prj_acme_demo");
  await expect(
    page.getByText("Latest status").locator("..").getByLabel("Status: completed"),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Latest findings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Latest recommendations" })).toBeVisible();
  await expect(page.locator(`a[href="/audits/${completedAuditId}"]`).first()).toBeVisible();
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
  await expect(page.getByRole("button", { name: /retry audit/i })).toHaveCount(0);
  await expect(page.getByText(/running the unchanged project again would repeat/i)).toBeVisible();
  await page.getByRole("link", { name: /create corrected project/i }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("dialog", { name: /create a project/i })).toBeVisible();
});

test("switching workspaces visibly preserves tenant isolation", async ({ page }) => {
  await signInAsAlice(page);
  await page.getByLabel("Viewing workspace").selectOption("usr_bob");
  await expect(page.getByRole("heading", { name: "Beta Finance" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Acme Skincare" })).toHaveCount(0);
});

test("direct project and audit URLs remain tenant scoped", async ({ page }) => {
  await signInAsAlice(page);
  await page.goto("/projects/prj_acme_demo");
  await page.getByRole("button", { name: /run new audit/i }).click();
  await expect(page).toHaveURL(/\/audits\/aud_[a-z0-9]+$/);
  const acmeAuditPath = new URL(page.url()).pathname;

  await page.getByLabel("Viewing workspace").selectOption("usr_bob");
  await expect(page.getByRole("heading", { name: "Beta Finance" })).toBeVisible();

  await page.goto("/projects/prj_acme_demo");
  await expect(page.getByText("Project not found")).toBeVisible();
  await page.goto(acmeAuditPath);
  await expect(page.getByText("Audit not found")).toBeVisible();
});

test("finding filters are reflected in the URL and can be cleared", async ({ page }) => {
  await signInAsAlice(page);
  await page.goto("/findings");

  await page.getByLabel("Severity").selectOption("high");
  await expect(page).toHaveURL(/severity=high/);
  await page.getByLabel("Category").selectOption("ai_visibility");
  await expect(page).toHaveURL(/severity=high.*category=ai_visibility/);
  await page.getByRole("searchbox", { name: "Project" }).fill("acmeskincare.com");
  await expect(page.locator('#finding-project option[value="prj_acme_demo"]')).toHaveCount(1);
  await page.getByLabel("Choose a project").selectOption("prj_acme_demo");
  await expect(page).toHaveURL(/project_id=prj_acme_demo/);
  const completedOption = page
    .locator("#finding-audit option")
    .filter({ hasText: "completed" })
    .first();
  await expect(completedOption).toHaveCount(1);
  const selectedAuditId = completedAuditId || (await completedOption.getAttribute("value")) || "";
  expect(selectedAuditId).not.toBe("");
  await page.getByLabel("Audit").selectOption(selectedAuditId);

  await expect
    .poll(() => {
      const params = new URL(page.url()).searchParams;
      return [
        params.get("severity"),
        params.get("category"),
        params.get("project_id"),
        params.get("audit_id"),
      ];
    })
    .toEqual(["high", "ai_visibility", "prj_acme_demo", selectedAuditId]);
  await expect(page.getByText("4 active filters")).toBeVisible();
  const matchingFinding = page.locator(".finding-card").filter({
    hasText: "Brand missing from a high-intent prompt",
  });
  await expect(matchingFinding).toHaveCount(1);
  await expect(matchingFinding.getByText("high", { exact: true })).toBeVisible();
  await expect(matchingFinding.getByText("ai visibility", { exact: true })).toBeVisible();
  await expect(matchingFinding.getByRole("link", { name: "Acme Skincare" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();

  await expect(page).toHaveURL(/\/findings$/);
  await expect(page.getByLabel("Severity")).toHaveValue("");
  await expect(page.getByLabel("Category")).toHaveValue("");
  await expect(page.getByLabel("Choose a project")).toHaveValue("");
  await expect(page.getByLabel("Audit")).toBeDisabled();
  await expect(page.getByText("Showing all findings")).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear filters" })).toBeDisabled();
});

test("sign out revokes the browser session and protects direct routes", async ({ page }) => {
  await signInAsAlice(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/projects/prj_acme_demo");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: /choose a test workspace/i })).toBeVisible();
});
