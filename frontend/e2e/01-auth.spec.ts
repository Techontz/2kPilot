import { expect, test } from "@playwright/test";
import { EMAIL, login, trackErrors } from "./helpers";

test("unauthenticated users are sent to login", async ({ page }) => {
  await page.goto("/risk");
  await expect(page).toHaveURL(/\/login\?next=%2Frisk/);
});

test("wrong password is refused with a generic message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form").getByRole("alert")).toHaveText("Invalid email or password");
});

test("owner can sign in and out; a fresh install is stopped in DEMO", async ({ page }) => {
  const errors = trackErrors(page);
  await login(page);
  await expect(page.getByRole("banner")).toContainText("Operating mode: Demo");
  await expect(page.getByRole("banner").getByText("Trading stopped").first()).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(errors).toEqual([]);
});
