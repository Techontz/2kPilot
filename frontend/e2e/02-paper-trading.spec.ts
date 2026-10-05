import { expect, test } from "@playwright/test";
import { fxOpenNow, login } from "./helpers";

test.describe.configure({ mode: "serial" });

test("add a Paper account through the 7-step wizard", async ({ page }) => {
  await login(page);
  await page.goto("/brokers/new");
  await page.getByRole("button", { name: /Paper Trading/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Demo or Live?")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel(/Start the simulation/).fill("0"); // start today: prices follow real time
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText("Connection works")).toBeVisible();
  await expect(page.getByText("Market and pending orders")).toBeVisible();
  await page.getByRole("switch", { name: /This is the account I want/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Assign a risk profile")).toBeVisible();
  await page.getByLabel("Name for this account").fill("E2E Paper");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Save account" }).click();
  await expect(page.getByRole("heading", { name: "E2E Paper added" })).toBeVisible();
  await expect(page.getByText("Connected and synced.")).toBeVisible();

  await page.goto("/brokers");
  const card = page.getByRole("article", { name: "E2E Paper account" });
  await expect(card.getByText("PAPER", { exact: true })).toBeVisible();
  await expect(card.getByText("Connected")).toBeVisible();
  await expect(card.getByText("10,000.00").first()).toBeVisible();
  await card.getByRole("switch", { name: "Trading enabled" }).click();
  await expect(card.getByText(/Strategies and manual tickets may trade/)).toBeVisible();
});

test("a risk profile that allows every session", async ({ page }) => {
  await login(page);
  await page.goto("/risk");
  await page.getByRole("button", { name: "New profile" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("E2E all sessions");
  await dialog.getByRole("button", { name: "asia" }).click();
  await dialog.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("E2E all sessions")).toBeVisible();
  await page.goto("/brokers");
  const saved = page.waitForResponse((r) => r.url().includes("/api/accounts/") && r.request().method() === "PATCH" && r.ok());
  await page.getByRole("article", { name: "E2E Paper account" }).getByLabel("Risk profile").selectOption({ label: "E2E all sessions" });
  await saved;
});

test("STOP TRADING blocks a manual ticket (risk rejection)", async ({ page }) => {
  await login(page);
  await page.goto("/trade");
  await expect(page.getByText("Trading is stopped")).toBeVisible();
  await expect(page.getByRole("radio", { name: /Buy \d/ })).toBeVisible(); // live price loaded
  await page.getByRole("button", { name: "20 pips", exact: true }).first().click(); // stop loss
  await expect(page.getByText(/Kill switch: STOP ALL TRADING is engaged/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Review order" })).toBeDisabled();
});

test("paper trade end to end: resume, buy, see the position, close it", async ({ page }) => {
  test.skip(!fxOpenNow(), "FX market is closed right now — the risk engine correctly refuses trades");
  await login(page);
  await page.getByRole("button", { name: /Resume trading/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Resume trading" }).click();
  await expect(page.getByRole("button", { name: "Stop trading" })).toBeVisible();

  await page.goto("/trade");
  await expect(page.getByRole("radio", { name: /Buy \d/ })).toBeVisible();
  await page.getByRole("button", { name: "20 pips", exact: true }).first().click();
  await page.getByRole("button", { name: "40 pips", exact: true }).click();
  await expect(page.getByText("Allowed by your risk profile")).toBeVisible();
  await page.getByRole("button", { name: /Use max allowed/ }).click();
  await page.getByRole("button", { name: "Review order" }).click();
  await expect(page.getByText("PAPER account — simulated execution, no real money.")).toBeVisible();
  await page.getByRole("button", { name: "Send buy order" }).click();
  await expect(page.getByText("PAPER order filled")).toBeVisible();

  await page.goto("/positions");
  await expect(page.getByRole("cell", { name: "EURUSD" })).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Close position" }).click();
  await expect(page.getByText("No open positions")).toBeVisible();

  await page.goto("/history");
  await expect(page.getByRole("cell", { name: "EURUSD" })).toBeVisible();
  await page.getByRole("cell", { name: "EURUSD" }).click();
  await expect(page.getByText("Risk decision")).toBeVisible();
  await expect(page.getByText(/Manual ticket/).first()).toBeVisible();

  await page.goto("/journal");
  await expect(page.getByRole("cell", { name: "Executed" })).toBeVisible();
  // Stop again: positions are never closed by STOP TRADING.
  await page.getByRole("button", { name: "Stop trading" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Stop trading" }).click();
  await expect(page.getByRole("button", { name: /Resume trading/ })).toBeVisible();
});
