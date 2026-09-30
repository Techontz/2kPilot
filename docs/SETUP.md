# Setup

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11+ | `python3.11 --version` |
| Node.js | 20+ (24 used in development) | `node --version` |
| PostgreSQL | 16 | `pg_isready` |

macOS (Homebrew): `brew install python@3.11 node postgresql@16 && brew services start postgresql@16`

> **MetaTrader 5 note:** the official `MetaTrader5` Python package only runs on **Windows**, next to an installed MT5 terminal. You can develop everything except the live MT5 connection on macOS or Linux. See [BROKERS.md](BROKERS.md).

## 1. Install dependencies

```bash
make setup
# equivalent to:
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
cd frontend && npm install
```

## 2. Configure the backend

```bash
cp .env.example backend/.env
backend/.venv/bin/fxrobot generate-key
```

Paste the generated key into `SECRET_ENCRYPTION_KEY` in `backend/.env`. **Back this key up securely.** If you lose it, stored broker credentials can't be decrypted.

Key settings:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localhost:5432/fxrobot` | SQLAlchemy URL |
| `SECRET_ENCRYPTION_KEY` | *(empty)* | Fernet key(s). Comma-separate to rotate (the newest goes first) |
| `LIVE_TRADING_ENABLED` | `false` | **Hard lock.** While false, LIVE mode can't be entered |
| `COOKIE_SECURE` | `false` | Must be `true` in production (HTTPS) |
| `LOG_FORMAT` | `json` | Use `console` for readable local logs |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Who may set `X-Forwarded-For` |

## 3. Create the database and run migrations

```bash
createdb fxrobot
make migrate            # alembic upgrade head
```

A fresh database starts in **DEMO** mode with the **kill switch engaged**.

## 4. Create your user

There is no public sign-up. Create the owner account from the CLI:

```bash
backend/.venv/bin/fxrobot create-user --email you@example.com --name "Your Name"
# prompts for a password: at least 12 characters, mixed case, a digit
# automation: echo "$PW" | fxrobot create-user --email … --name … --password-stdin
```

Use `--role viewer` for read-only users.

## 5. Run

```bash
make backend    # http://127.0.0.1:8000  (interactive API docs: /api/docs)
make frontend   # http://localhost:3000
```

The frontend proxies `/api/v1/*` to `BACKEND_URL` (default `http://127.0.0.1:8000`). If you change the backend port, set `BACKEND_URL` in `frontend/.env.local`. For production builds, set it **before** `npm run build`, because rewrites are resolved at build time.

## 6. Verify

```bash
curl http://127.0.0.1:8000/api/v1/health/ready
# {"status":"ok","checks":{"database":"ok","migrations":"ok"}}
make check
```

## Tests need a test database

```bash
createdb fxrobot_test          # or set TEST_DATABASE_URL
```

The test suite migrates this database from scratch on each run. That means it tests the migrations too.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health/ready` shows `"migrations":"pending"` | Run `make migrate` |
| Login says "Too many login attempts" | Wait for the `Retry-After` period (15 min by default), or restart the backend in development |
| Dashboard says "Cannot reach the 2kFX server" | The backend isn't running, or `BACKEND_URL` is wrong |
| Port already in use | Pick another port: `uvicorn … --port 8421` and `BACKEND_URL=http://127.0.0.1:8421` |
