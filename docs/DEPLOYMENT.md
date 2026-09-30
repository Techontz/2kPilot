# Deployment

> 2kFX is designed for a single operator on a private machine or VPS. Don't expose it to the internet without HTTPS, and ideally not before MFA exists.

## Recommended topology

```
[your browser] ──HTTPS──► [Linux/macOS/Windows host: Next.js + FastAPI (engine) + MySQL 8]
                                          │ Tailscale / WireGuard / TLS, HMAC
                                          ▼
                          [Windows PC/VPS: mt5_bridge + MetaTrader 5 terminal]
```

The whole stack can also run on the Windows VPS itself. The bridge then listens on `127.0.0.1` only.

## Native (verified)

```bash
make setup && make db && make user EMAIL=… NAME=…
make build BACKEND_PORT=8000
cd backend && .venv/bin/uvicorn fxrobot.main:create_app --factory --no-proxy-headers --host 127.0.0.1 --port 8000
cd frontend && npx next start -p 3000
```

Run **one** backend process. It hosts the trading engine; a database lease prevents a second engine from trading, but the event stream and login rate limiter are per-process. Put a reverse proxy (Caddy or nginx) in front of Next.js for HTTPS, then set `APP_ENV=production` and `COOKIE_SECURE=true`.

## Docker Compose

```bash
cp .env.example backend/.env   # set SECRET_ENCRYPTION_KEY; DATABASE_URL is overridden by compose
docker compose up --build
docker compose exec backend fxrobot create-user --email you@example.com --name "You"
```

The stack is MySQL 8.0 (volume `mysqldata`), a backend that migrates on start and runs as a non-root user, and a Next.js standalone frontend. Ports are bound to `127.0.0.1`.

> Docker was not available on the development machine, so the Compose setup is **written but not run**. The native setup is the verified path.

## Health checks

| Endpoint | Meaning |
|---|---|
| `GET /api/v1/health/live` | The process is up |
| `GET /api/v1/health/ready` | The database is reachable and the schema is at the latest migration (503 otherwise) |
| Top bar / `GET /api/v1/trading/status` | Engine heartbeat: `running` / `degraded` / `offline` |

## Backups

* **MySQL.** Take regular `mysqldump --single-transaction` dumps of the `fxrobot` schema, and test a restore.
* **`SECRET_ENCRYPTION_KEY`.** Store it separately from the database backup.
* **`mt5_bridge` journal** (`JOURNAL_PATH`, SQLite). Keep it with the bridge; it provides idempotency across restarts.

## Production checklist

- [ ] `APP_ENV=production`, `COOKIE_SECURE=true`, HTTPS in front
- [ ] Dedicated MySQL user, not root; automated backups
- [ ] Encryption key in a password manager and backed up
- [ ] Bridge on a private network or TLS, firewall rule, long `BRIDGE_SECRET`
- [ ] `LIVE_TRADING_ENABLED=false` until the live-readiness review is signed off
- [ ] `LOG_FORMAT=json`, logs retained
