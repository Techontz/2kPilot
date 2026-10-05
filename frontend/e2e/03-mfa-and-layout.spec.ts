import { expect, test } from "@playwright/test";
import { E2E_USER } from "../playwright.config";
import { login, totp } from "./helpers";

const PAGES = ["/", "/markets", "/trade", "/strategies", "/backtesting", "/positions", "/orders", "/history", "/brokers", "/brokers/new", "/analytics", "/risk", "/journal", "/notifications", "/settings"];

test("every page renders on desktop and mobile without errors or sideways scrolling", async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => m.type() === "error" && errors.push(`${page.url()}: ${m.text()}`));
    await login(page);
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("banner").getByRole("button", { name: /Stop trading|Resume/ })).toBeVisible(); // always reachable
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path} at ${viewport.width}px`).toBeLessThanOrEqual(1);
    }
    expect(errors).toEqual([]);
    await context.close();
  }
});

test("turn on MFA, then sign in with a one-time code", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  await page.getByLabel("Confirm your password").fill(E2E_USER.password);
  await page.getByRole("button", { name: "Set up two-factor authentication" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Code", { exact: true }).fill(totp(secret));
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByText("Save these recovery codes now")).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.waitForTimeout(31_000); // next 30-second window: a fresh, unused code
  await login(page, () => totp(secret));
  await expect(page.getByText("turn on two-factor authentication")).toHaveCount(0);
});
