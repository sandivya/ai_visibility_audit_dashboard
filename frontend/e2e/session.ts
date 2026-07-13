import { expect, type Page } from "@playwright/test";

export async function signInAs(page: Page, workspace: RegExp) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /choose a test workspace/i })).toBeVisible();
  await page.getByRole("button", { name: workspace }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
}

export async function signInAsAlice(page: Page) {
  await signInAs(page, /Acme Skincare.*alice@acme\.com/i);
}
