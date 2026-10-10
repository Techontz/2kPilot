import { expect, test } from "@playwright/test";
import { E2E_USER } from "../playwright.config";
import { login, totp } from "./helpers";

const PAGES = [
  "/",
  "/strategies", "/strategies?tab=templates", "/strategies?tab=backtests",
  "/history", "/history?tab=closed", "/history?tab=activity",
  "/settings", "/settings?tab=accounts", "/settings?tab=risk", "/settings?tab=notifications", "/settings?tab=security", "/settings?tab=system",
  "/settings/brokers/new",
];

/** Old URLs land in the right section. */
const LEGACY = {
  "/positions": "/history?tab=open",
  "/orders": "/history?tab=activity",
  "/journal": "/history?tab=activity",
  "/analytics": "/history?tab=closed",
  "/markets": "/",
  "/trade": "/",
  "/backtesting": "/strategies?tab=backtests",
  "/brokers": "/settings?tab=brokers",
  "/brokers/new": "/settings/brokers/new",
  "/risk": "/settings?tab=risk",
  "/notifications": "/settings?tab=notifications",
};

test("legacy URLs redirect into the four sections", async ({ page }) => {
  await login(page);
  for (const [from, to] of Object.entries(LEGACY)) {
    await page.goto(from);
    await expect(page, from).toHaveURL(new URL(to, page.url()).href);
  }
});

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
      // The live-update stream keeps a request open, so "networkidle" never comes.
      await page.waitForLoadState("load");
      await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 20_000 });
      await expect(page.getByRole("banner").getByRole("button", { name: /Stop trading|Start trading/ })).toBeVisible(); // always reachable
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path} at ${viewport.width}px`).toBeLessThanOrEqual(1);
    }
    expect(errors).toEqual([]);
    await context.close();
  }
});

test("turn on MFA, then sign in with a one-time code", async ({ page }) => {
  await login(page);
  await page.goto("/settings?tab=security");
  await page.getByLabel("Confirm your password").fill(E2E_USER.password);
  await page.getByRole("button", { name: "Set up two-factor authentication" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Code", { exact: true }).fill(totp(secret));
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByText("Save these recovery codes now")).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.waitForTimeout(31_000); // next 30-second window: a fresh, unused code
  await login(page, () => totp(secret));
  await expect(page.getByText("turn on two-factor authentication")).toHaveCount(0);
});
