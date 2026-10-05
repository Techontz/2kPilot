import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("protected pages redirect to login, and wrong passwords are refused", async ({ page }) => {
  await page.goto("/brokers");
  await expect(page).toHaveURL(/\/login\?next=%2Fbrokers/);
  await page.getByLabel("Email").fill("e2e@2kfx.local");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Email or password is incorrect.")).toBeVisible();
});

test("login shows the welcome path and the always-visible controls", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: /Welcome to 2kFX/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Resume trading/ })).toBeVisible(); // fresh install: stopped
  await expect(page.getByText("turn on two-factor authentication")).toBeVisible();
});
