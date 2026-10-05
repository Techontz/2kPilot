import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";
import { E2E_USER } from "../playwright.config";

export async function login(page: Page, code?: () => string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(E2E_USER.email);
  await page.getByLabel("Password").fill(E2E_USER.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (code) {
    await expect(page.getByText("Two-step sign-in")).toBeVisible();
    await page.getByLabel("Code", { exact: true }).fill(code());
    await page.getByRole("button", { name: "Verify and sign in" }).click();
  }
  await expect(page).toHaveURL(/\/$/);
}

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits) — what an authenticator app shows. */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30000)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 0xf;
  const value = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return value.toString().padStart(6, "0");
}

/** Retail FX hours (Sunday 21:00 – Friday 21:00 UTC), as the risk engine applies them. */
export function fxOpenNow(now = new Date()): boolean {
  const day = now.getUTCDay();
  const hour = now.getUTCHours();
  if (day === 6) return false;
  if (day === 5 && hour >= 21) return false;
  return !(day === 0 && hour < 21);
}
