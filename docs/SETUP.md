# Setup

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python3.11 --version` |
| Node.js | 20+ (24 used in development) | `node --version` |
| MySQL | **8.x** (9.x also works) | Any reachable server; `make db` creates the database |
| Google Chrome | any recent | Only for `make e2e` |

MetaTrader 5 is **not** needed on this machine. The MT5 terminal and the `mt5_bridge` run on Windows. See [MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md).

## 1. Install

```bash
make setup
```

This does four things:
1. Creates `backend/.venv`.
2. Installs the backend.
3. Installs the frontend packages.
4. Creates `backend/.env` from `.env.example` with a **freshly generated** `SECRET_ENCRYPTION_KEY`.

An existing `.env` is never overwritten.

> **Back up `SECRET_ENCRYPTION_KEY`.** It encrypts broker passwords. If you lose it, saved MT5 connections must be re-entered.

## 2. Point at your MySQL

Edit `DATABASE_URL` in `backend/.env`:

```
DATABASE_URL=mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fxrobot?charset=utf8mb4
```

The database user needs these privileges on that schema:
* CREATE, ALTER, INDEX, REFERENCES, and SELECT/INSERT/UPDATE/DELETE.
* **TRIGGER**. The audit log is protected by triggers.

If binary logging is on and the user lacks SUPER, set `log_bin_trust_function_creators=1`. Managed MySQL services such as RDS need this.

> On the development machine this project was built on, MySQL 8.0.46 listens on **127.0.0.1:3308** and MySQL 9.3 on 3306. `backend/.env` there points at 3308.

## 3. Create the database and your login

```bash
make db                                        # creates `fxrobot` (utf8mb4) if missing + migrations
make user EMAIL=you@example.com NAME=Conrad    # prompts twice for a password (≥12 chars, mixed case, digit)
```

There is no public sign-up. Use `make user … ` again with a different `EMAIL` for more users. Add `--role viewer` via `backend/.venv/bin/fxrobot create-user` for a read-only user.

## 4. Run

```bash
make dev                                   # API + trading engine on :8000, dashboard on :3000
make dev BACKEND_PORT=8421 FRONTEND_PORT=3421   # if those ports are taken
```

Open http://localhost:3000 (or your port). The interactive API docs are at `http://127.0.0.1:8000/api/docs`.

Separately: `make backend` (auto-reload) and `make frontend`.

## 5. Verify

```bash
curl http://127.0.0.1:8000/api/v1/health/ready
# {"status":"ok","checks":{"database":"ok","migrations":"ok"}}
make check      # lint, types, all unit/integration tests, migration drift check
make e2e        # browser end-to-end tests (uses database fxrobot_e2e — dropped and recreated)
```

### Test databases

* **Backend tests** use `TEST_DATABASE_URL`, which defaults to `mysql+pymysql://root@127.0.0.1:3308/fxrobot_test`. The database is created if missing and migrated from scratch on every run.
* **E2E tests** use `E2E_DATABASE_URL`, which defaults to `fxrobot_e2e` on the same server. The script refuses any database whose name doesn't end in `_e2e`.

## Configuration reference (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://root@127.0.0.1:3306/fxrobot?charset=utf8mb4` | MySQL connection |
| `SECRET_ENCRYPTION_KEY` | — | Fernet key(s). To rotate, put the new key first: `new,old` |
| `LIVE_TRADING_ENABLED` | `false` | **Hard lock.** LIVE is impossible while false |
| `ENGINE_ENABLED` | `true` | Run the trading engine inside the API process |
| `ENGINE_TICK_SECONDS` | `2` | How often the engine reconciles and evaluates |
| `BACKTEST_WORKERS` | `1` | Parallel backtests |
| `APP_ENV` | `development` | `production` enforces secure cookies and a set key |
| `LOG_FORMAT` / `LOG_LEVEL` | `json` / `INFO` | `console` for readable local logs |
| `COOKIE_SECURE` | `false` | Must be `true` behind HTTPS |
| `SESSION_TTL_MINUTES` / `SESSION_IDLE_TIMEOUT_MINUTES` | 720 / 60 | Session lifetime |
| `LOGIN_RATE_LIMIT_ATTEMPTS` / `…_WINDOW_SECONDS` | 5 / 900 | Brute-force protection |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Who may set `X-Forwarded-For` |
| `CORS_ORIGINS` | empty | Only for direct API use (the dashboard is same-origin) |

Frontend: `BACKEND_URL` (server-side only) tells Next.js where to proxy `/api/v1/*`. For production builds, set it **before** `npm run build`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health/ready` shows `"migrations":"pending"` | `make migrate` |
| Top bar says **Robot offline** | The backend isn't running, or it runs with `ENGINE_ENABLED=false` |
| MT5 connection test fails | See [MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md#troubleshooting) |
| "SECRET_ENCRYPTION_KEY is not configured" when saving MT5 | `make env`, or add a key to `backend/.env` |
| Port already in use | `make dev BACKEND_PORT=… FRONTEND_PORT=…` |
| A migration failed half-way | MySQL DDL is not transactional. Restore the backup, or drop the half-created tables, before retrying |
