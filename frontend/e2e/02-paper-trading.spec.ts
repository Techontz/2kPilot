import { expect, test } from "@playwright/test";
import { type APIRequestContext, type Page } from "@playwright/test";
import { login } from "./helpers";

test.describe.configure({ mode: "serial" });

test("add a Paper account through the 7-step wizard", async ({ page }) => {
  await login(page);
  await page.goto("/settings/brokers/new");
  await page.getByRole("button", { name: /Paper Trading/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Demo or Live?")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  // Synthetic indices trade 24/7; a 2-day head start replays bars quickly (one every 2 s).
  await page.getByLabel("Symbols").fill("R_100,EURUSD");
  await page.getByLabel(/Start the simulation/).fill("2");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText("Connection works")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Market and pending orders")).toBeVisible();
  await page.getByRole("switch", { name: /This is the account I want/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Assign a risk profile")).toBeVisible();
  await page.getByLabel("Name for this account").fill("E2E Paper");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Save account" }).click();
  await expect(page.getByRole("heading", { name: "E2E Paper added" })).toBeVisible();
  await expect(page.getByText("Connected and synced.")).toBeVisible();

  await page.goto("/settings?tab=brokers");
  const card = page.getByRole("article", { name: "E2E Paper account" });
  await expect(card.getByText("PAPER", { exact: true })).toBeVisible();
  await expect(card.getByText("Connected")).toBeVisible();
  await expect(card.getByText("10,000.00").first()).toBeVisible();

  // Trading on/off and the risk profile live on the Accounts tab.
  await page.goto("/settings?tab=accounts");
  const settings = page.getByRole("article", { name: "E2E Paper account" });
  await settings.getByRole("switch", { name: "Trading enabled" }).click();
  await expect(settings.getByText(/Strategies and manual tickets may trade/)).toBeVisible();
});

test("start asks for confirmation; stop is one click", async ({ page }) => {
  await login(page);
  const banner = page.getByRole("banner");
  await banner.getByRole("button", { name: "Start trading" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Start trading" }).click();
  await banner.getByRole("button", { name: "Stop trading" }).click();
  await expect(banner.getByRole("button", { name: "Start trading" })).toBeVisible();
});

test("a risk profile that allows every session", async ({ page }) => {
  await login(page);
  await page.goto("/settings?tab=risk");
  await page.getByRole("button", { name: "New profile" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("E2E all sessions");
  await dialog.getByRole("button", { name: "Advanced (Spot trading on Paper)" }).click();
  await dialog.getByRole("button", { name: "asia" }).click();
  await dialog.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("E2E all sessions")).toBeVisible();
  await page.goto("/settings?tab=accounts");
  const saved = page.waitForResponse((r) => r.url().includes("/api/accounts/") && r.request().method() === "PATCH" && r.ok());
  await page.getByRole("article", { name: "E2E Paper account" }).getByRole("combobox", { name: "Risk profile" }).click();
  await page.getByRole("option", { name: "E2E all sessions" }).click();
  await saved;
});

/** Same-origin API call with the page's session cookie and CSRF token (setup only). */
async function apiCall(page: Page, method: "GET" | "POST", path: string, data?: unknown) {
  const request: APIRequestContext = page.request;
  const cookies = await page.context().cookies();
  const xsrf = decodeURIComponent(cookies.find((c) => c.name === "XSRF-TOKEN")?.value ?? "");
  const response = await request.fetch(`/api${path}`, {
    method,
    data,
    headers: { Accept: "application/json", "X-XSRF-TOKEN": xsrf, "X-Requested-With": "XMLHttpRequest", Referer: page.url() },
  });
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

test("paper strategy runs end-to-end in demo", async ({ page }) => {
  await login(page);
  // A deliberately trivial rule set so a trade happens quickly (Method B's save path).
  await apiCall(page, "POST", "/strategies", {
    name: "E2E every candle",
    source: "builder",
    rules: { schema_version: 1, timeframe: "M15", entry: { buy: { all: [{ left: { price: "close" }, op: "gt", right: { value: 0 } }] } } },
  });

  // Activate it from its card: account, market and a 15-minute Rise/Fall.
  await page.goto("/strategies");
  const card = page.locator("[data-slot=card]", { hasText: "E2E every candle" });
  await card.getByRole("button", { name: "Activate" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Market" }).click();
  await page.getByRole("option", { name: /R_100/ }).click();
  await dialog.getByLabel("Lasts for").fill("15");
  await dialog.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(dialog.getByText("E2E every candle is active")).toBeVisible();
  await expect(dialog.getByText("Trading is stopped — press Start when you are ready.")).toBeVisible(); // honest blockers
  await dialog.getByRole("button", { name: "Start trading" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Start trading" }).click();
  await expect(page.getByRole("banner").getByRole("button", { name: "Stop trading" })).toBeVisible();

  // The engine evaluates the rules and the risk engine approves a contract.
  await page.goto("/history?tab=activity");
  await expect(page.getByText(/Risk approved CALL/).first()).toBeVisible({ timeout: 120_000 });
  await page.goto("/history?tab=open");
  await expect(page.getByText("R_100").first()).toBeVisible({ timeout: 60_000 });
  await page.goto("/");
  await expect(page.getByText("Active strategies", { exact: true })).toBeVisible();
  await expect(page.getByText("E2E every candle", { exact: true }).first()).toBeVisible();
});

test("STOP blocks new automated trades", async ({ page }) => {
  await login(page);
  const banner = page.getByRole("banner");
  await banner.getByRole("button", { name: "Stop trading" }).click(); // one click, no dialog
  await expect(banner.getByRole("button", { name: "Start trading" })).toBeVisible();
  await expect(page.getByText("Trading is stopped — press Start when you are ready.")).toBeVisible();

  const count = async () => {
    const signals = await apiCall(page, "GET", "/signals?per_page=100");
    return (signals.data as { status: string }[]).filter((s) => s.status === "EXECUTED").length;
  };
  await page.waitForTimeout(3000); // let an in-flight tick finish
  const before = await count();
  await page.waitForTimeout(15_000); // several simulated bars close meanwhile
  expect(await count()).toBe(before);

  // History still shows every trade, with the CSV export of the current filters.
  await page.goto("/history?tab=closed");
  await page.getByLabel("Period").click();
  await page.getByRole("option", { name: "All time" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^2kpilot-history-\d{8}\.csv$/);
});
