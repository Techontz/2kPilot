import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("protected pages redirect to login, and wrong passwords are refused", async ({ page }) => {
  await page.goto("/brokers"); // legacy URL → /settings?tab=brokers → sign-in
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%3Ftab%3Dbrokers/);
  await page.getByLabel("Email").fill("e2e@tradepilot.local");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Email or password is incorrect.")).toBeVisible();
});

test("login shows the welcome path and the always-visible controls", async ({ page }) => {
  await login(page);
  await expect(page.getByText("Get started in four steps")).toBeVisible();
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("button", { name: "Start trading" })).toBeVisible(); // new users start stopped
  await expect(banner.getByText("DEMO", { exact: true })).toBeVisible(); // demo is the default mode

  // Exactly four sections in the main navigation.
  const nav = page.getByRole("navigation", { name: "Main" }).first();
  await expect(nav.getByRole("link")).toHaveText([/Home/, /Strategies/, /History/, /Settings/]);
  await expect(page.getByText("turn on two-factor authentication")).toBeVisible();
});
