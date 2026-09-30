import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("generate synthetic data and run a backtest", async ({ page }) => {
  await login(page);
  await page.goto("/markets");
  await page.getByRole("button", { name: "Synthetic" }).click();
  const dialog = page.locator("dialog[open]");
  await expect(dialog.getByText("Not real market data")).toBeVisible();
  await dialog.locator("label", { hasText: "Days of history" }).locator("input").fill("300");
  await dialog.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("cell", { name: "SYNTHETIC" })).toBeVisible({ timeout: 60_000 });

  await page.goto("/backtesting");
  await page.getByRole("button", { name: "New backtest" }).click();
  await page.locator("dialog[open]").getByRole("button", { name: "Run backtest" }).click();
  await expect(page.getByText("Equity curve")).toBeVisible({ timeout: 200_000 });
  await expect(page.getByText("SYNTHETIC data: these results say nothing about real markets.")).toBeVisible();
  await expect(page.getByText("Historical results do not guarantee future performance.")).toBeVisible();
  await expect(page.getByText("Run details")).toBeVisible();
});
