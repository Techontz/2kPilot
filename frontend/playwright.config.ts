import { execFileSync } from "node:child_process";
import path from "node:path";
import { defineConfig } from "@playwright/test";

/**
 * Browser E2E tests against the REAL backend (MySQL) and the production frontend build.
 * Run with `make e2e` (or `npm run e2e`). Uses the locally installed Google Chrome.
 * The database named by E2E_DATABASE_URL is dropped and recreated.
 */
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8431);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3431);
const DB = process.env.E2E_DATABASE_URL ?? "mysql+pymysql://root@127.0.0.1:3308/fxrobot_e2e?charset=utf8mb4";
const backendDir = path.resolve(__dirname, "../backend");

if (!process.env.E2E_SKIP_PREPARE) {
  execFileSync(path.join(backendDir, ".venv/bin/python"), ["scripts/e2e_prepare.py"], {
    cwd: backendDir,
    env: { ...process.env, E2E_DATABASE_URL: DB },
    stdio: "inherit",
  });
  process.env.E2E_SKIP_PREPARE = "1"; // workers re-evaluate this file; prepare only once
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `.venv/bin/uvicorn fxrobot.main:create_app --factory --no-proxy-headers --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/health/ready`,
      env: { DATABASE_URL: DB, ENGINE_TICK_SECONDS: "1", LOG_FORMAT: "console", LOG_LEVEL: "WARNING" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run build && npx next start -H 127.0.0.1 -p ${FRONTEND_PORT}`,
      env: { BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}` },
      url: `http://127.0.0.1:${FRONTEND_PORT}/login`,
      timeout: 300_000,
      reuseExistingServer: false,
    },
  ],
});
