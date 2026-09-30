import { expect, test } from "@playwright/test";
import { login, trackErrors } from "./helpers";

test("LIVE mode cannot be selected while the server lock is on", async ({ page }) => {
  await login(page);
  await page.goto("/trading");
  await expect(page.getByRole("radio", { name: /LIVE/ })).toBeDisabled();
  await expect(page.getByText(/LIVE is disabled on this server/)).toBeVisible();
});

test("glossary explains terms for beginners", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Equity" }).first().hover();
  await expect(page.getByRole("tooltip")).toContainText("what the account is worth right now");
});

const PAGES = ["/", "/markets", "/strategies", "/backtesting", "/trading", "/positions", "/orders", "/history",
  "/brokers", "/analytics", "/risk", "/journal", "/notifications", "/settings"];

test("every page renders without console errors or horizontal overflow on mobile", async ({ page }) => {
  const errors = trackErrors(page);
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});
