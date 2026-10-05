import { execSync } from "node:child_process";
import path from "node:path";
import { defineConfig } from "@playwright/test";

/**
 * Browser E2E tests against the REAL stack — Laravel + trading engine + MySQL +
 * the production Next.js build — in the locally installed Google Chrome.
 * Run with `make e2e`. The E2E database (twokfx_e2e) is recreated every run.
 */
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8432);
const ENGINE_PORT = Number(process.env.E2E_ENGINE_PORT ?? 8433);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3432);
const DB_PORT = process.env.E2E_DB_PORT ?? "3308";
const DB_NAME = "twokfx_e2e";
const backendDir = path.resolve(__dirname, "../backend");
const engineDir = path.resolve(__dirname, "../trading-engine");
export const E2E_USER = { email: "e2e@2kfx.local", password: "E2e-Verify-Passw0rd" };

const laravelEnv = {
  DB_PORT,
  DB_DATABASE: DB_NAME,
  ENGINE_URL: `http://127.0.0.1:${ENGINE_PORT}`,
  FRONTEND_URL: `http://127.0.0.1:${FRONTEND_PORT}`,
  SANCTUM_STATEFUL_DOMAINS: `127.0.0.1:${FRONTEND_PORT},localhost:${FRONTEND_PORT}`,
  APP_URL: `http://127.0.0.1:${BACKEND_PORT}`,
  LOG_LEVEL: "warning",
  FX_LOGIN_ATTEMPTS: "200", // the suite signs in many times; production keeps 5
  PHP_CLI_SERVER_WORKERS: "4",
};

if (!process.env.E2E_SKIP_PREPARE) {
  execSync(`mysql -h127.0.0.1 -P${DB_PORT} -uroot -e "DROP DATABASE IF EXISTS ${DB_NAME}; CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"`);
  execSync("php artisan migrate:fresh --force --no-interaction", { cwd: backendDir, env: { ...process.env, ...laravelEnv }, stdio: "inherit" });
  execSync(`php artisan fx:user --email=${E2E_USER.email} --name="E2E Owner" --password-stdin`, {
    cwd: backendDir, env: { ...process.env, ...laravelEnv }, input: `${E2E_USER.password}\n`, stdio: ["pipe", "inherit", "inherit"],
  });
  process.env.E2E_SKIP_PREPARE = "1"; // workers re-evaluate this file; prepare only once
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
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
      command: `.venv/bin/fxrobot serve --port ${ENGINE_PORT}`,
      cwd: engineDir,
      url: `http://127.0.0.1:${ENGINE_PORT}/internal/health/live`,
      env: { DATABASE_URL: `mysql+pymysql://root@127.0.0.1:${DB_PORT}/${DB_NAME}?charset=utf8mb4`, ENGINE_TICK_SECONDS: "1", LOG_LEVEL: "WARNING" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: `php artisan serve --host=127.0.0.1 --port=${BACKEND_PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${BACKEND_PORT}/up`,
      env: laravelEnv,
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
