import { expect, test } from "@playwright/test";
import { expectNoSeriousAccessibilityViolations } from "./accessibility";
import { attachReviewScreenshot } from "./review-artifacts";
import { signInAsAlice } from "./session";

test("the project workspace remains usable at a mobile viewport", async ({ page }, testInfo) => {
  await signInAsAlice(page);

  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("button", { name: /new project/i })).toBeVisible();

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
  await expectNoSeriousAccessibilityViolations(page);
  await attachReviewScreenshot(page, testInfo, "projects-mobile");
});
