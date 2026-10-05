# Setup (macOS / Linux)

You need: **PHP 8.4** with `pdo_mysql`, **Composer**, **Python 3.11**, **Node.js 20+**, **MySQL 8**, and Google Chrome (for the browser tests).

## 1. Install

```bash
make setup
```

This installs Laravel's packages, creates `backend/.env` (with a new `APP_KEY`), creates the Python virtual environment for the trading engine, copies `trading-engine/.env`, writes the two shared secrets (`BROKER_CREDENTIALS_KEY`, `ENGINE_API_SECRET`) into **both** env files, and installs the frontend.

## 2. Point both services at MySQL

`backend/.env`:

```
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=twokfx
DB_USERNAME=root
DB_PASSWORD=
```

`trading-engine/.env` (same database):

```
DATABASE_URL=mysql+pymysql://root@127.0.0.1:3306/twokfx?charset=utf8mb4
```

Create the database once: `mysql -uroot -e "CREATE DATABASE twokfx CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"`.

## 3. Create the tables and your login

```bash
make db                                   # php artisan migrate
make user EMAIL=you@example.com NAME=Conrad   # asks for a password (12+ chars, mixed case, a number)
```

## 4. Run

```bash
make dev
```

Starts the trading engine (127.0.0.1:8431), the Laravel API (127.0.0.1:8421), the queue worker, the scheduler and the dashboard. Open **http://localhost:3421** and sign in. Ports: `make dev BACKEND_PORT=… ENGINE_PORT=… FRONTEND_PORT=…` (if you change `FRONTEND_PORT`, also update `SANCTUM_STATEFUL_DOMAINS` and `FRONTEND_URL` in `backend/.env`).

## 5. First things to do

1. **Settings → Security**: turn on two-factor authentication.
2. **Brokers → Add broker → Paper Trading** — learn without real money ([USER_GUIDE.md](USER_GUIDE.md)).
3. Later: Deriv or MetaTrader 5 demo ([BROKERS.md](BROKERS.md)).

## Optional settings (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_TRADING_ENABLED` | `false` | Hard lock for real money. Set it in **both** env files. |
| `FX_REQUIRE_MFA` | `false` | Force every user to enrol in MFA |
| `FX_LOGIN_ATTEMPTS` | `5` | Failed sign-ins allowed per email+IP per 15 min |
| `DERIV_APP_ID` | — | Your Deriv App ID (also in `trading-engine/.env`) |
| `DERIV_OAUTH_REDIRECT_URL` | `http://localhost:3421/api/brokers/deriv/oauth/callback` | Must match the redirect URI registered at Deriv |

## Docker

`docker compose up --build` runs MySQL, Laravel (API, worker, scheduler), the engine and the dashboard (http://127.0.0.1:3000). Fill both env files first.
