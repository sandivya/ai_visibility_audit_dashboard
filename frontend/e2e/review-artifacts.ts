import type { Page, TestInfo } from "@playwright/test";

export async function attachReviewScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, {
    body: await page.screenshot({
      animations: "disabled",
      fullPage: true,
    }),
    contentType: "image/png",
  });
}
