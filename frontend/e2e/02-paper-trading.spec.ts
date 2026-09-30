import { expect, test } from "@playwright/test";
import { login, trackErrors } from "./helpers";

test.describe.serial("paper account → strategy → engine", () => {
  test("add a PAPER account through the wizard", async ({ page }) => {
    const errors = trackErrors(page);
    await login(page);
    await page.goto("/brokers");
    await expect(page.getByText("No broker connected yet")).toBeVisible();
    await page.getByRole("button", { name: "Add broker" }).first().click();
    const dialog = page.locator("dialog[open]");
    await dialog.getByText("Paper / Simulation (internal)").click();
    await dialog.getByRole("button", { name: "Continue" }).click();
    await dialog.getByPlaceholder("Paper account").fill("E2E Paper");
    await dialog.locator("label", { hasText: "Simulation speed" }).locator("input").fill("0.5");
    await dialog.getByRole("button", { name: "Continue" }).click();
    await dialog.getByRole("button", { name: "Test connection" }).click();
    await expect(dialog.getByText("Connected and verified")).toBeVisible();
    await expect(dialog.getByText("The broker confirms this is a PAPER account")).toBeVisible();
    await dialog.getByText("Yes, this is the account I want to connect.").click();
    await dialog.getByRole("button", { name: "Continue" }).click();
    await dialog.getByRole("button", { name: "Continue" }).click();
    await dialog.getByRole("button", { name: "Save account" }).click();
    await expect(page.getByText("E2E Paper added")).toBeVisible();
    // Saved with trading DISABLED.
    await expect(page.getByRole("switch", { name: /Trading enabled/ })).toHaveAttribute("aria-checked", "false");
    await page.getByRole("switch", { name: /Trading enabled/ }).click();
    await expect(page.getByRole("switch", { name: /Trading enabled/ })).toHaveAttribute("aria-checked", "true");
    expect(errors).toEqual([]);
  });

  test("assign the strategy (created paused), enable it and resume trading", async ({ page }) => {
    await login(page);
    await page.goto("/strategies");
    await page.getByRole("button", { name: "Assign" }).click();
    const dialog = page.locator("dialog[open]");
    await dialog.locator("label", { hasText: "Symbol" }).locator("select").selectOption("EURUSD");
    await dialog.getByRole("button", { name: "Assign (paused)" }).click();
    await expect(page.getByText("EURUSD on E2E Paper")).toBeVisible();
    const row = page.getByRole("listitem").filter({ hasText: "EURUSD on E2E Paper" });
    await expect(row.getByText("Paused", { exact: true })).toBeVisible();
    await row.getByRole("button", { name: "Enable" }).click();
    await expect(row.getByText("Enabled", { exact: true })).toBeVisible();
    await page.getByRole("banner").getByRole("button", { name: "Resume trading" }).click();
    await page.locator("dialog[open]").getByRole("button", { name: "Resume trading" }).click();
    await expect(page.getByRole("banner").getByRole("button", { name: "STOP ALL TRADING" })).toBeVisible();
  });

  test("the engine runs the pipeline and journals its decisions", async ({ page }) => {
    await login(page);
    await expect(page.getByRole("banner").getByText("Running").first()).toBeVisible({ timeout: 30_000 });
    // Poll the journal (through the same-origin proxy) until the engine has evaluated a signal.
    await expect
      .poll(async () => {
        const res = await page.request.get("/api/v1/journal?limit=50");
        const events = (await res.json()) as { event_type: string }[];
        return events.some((e) => e.event_type === "SIGNAL_GENERATED");
      }, { timeout: 200_000, intervals: [3000] })
      .toBe(true);
    await page.goto("/journal");
    await expect(page.getByText(/signal \(Trend Pullback V1/).first()).toBeVisible();
    await page.goto("/trading");
    await expect(page.getByText("Latest signals")).toBeVisible();
  });

  test("STOP ALL TRADING blocks new orders in one click", async ({ page }) => {
    await login(page);
    await page.getByRole("banner").getByRole("button", { name: "STOP ALL TRADING" }).click();
    await expect(page.getByRole("banner").getByText("Trading stopped").first()).toBeVisible();
    await page.goto("/risk");
    await expect(page.getByText("All trading is stopped")).toBeVisible();
  });
});
