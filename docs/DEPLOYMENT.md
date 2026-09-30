# Deployment

> Phase 1 is meant for local and private use. Don't expose the system to the internet before MFA and HTTPS are in place (see [SECURITY.md](SECURITY.md)).

## Docker Compose

```bash
cp .env.example backend/.env    # set SECRET_ENCRYPTION_KEY
docker compose up --build
docker compose exec backend fxrobot create-user --email you@example.com --name "You"
```

* `db`: PostgreSQL 16 with a named volume (`pgdata`).
* `backend`: runs `alembic upgrade head`, then uvicorn on port 8000 as a non-root user. It's bound to `127.0.0.1` on the host.
* `frontend`: a Next.js standalone server on port 3000, built with `BACKEND_URL=http://backend:8000`. Rewrites are resolved at build time.

> The Compose files were written for Phase 1 but **haven't been run yet**, because Docker isn't installed on the development machine. The native setup ([SETUP.md](SETUP.md)) is the verified path.

With Compose, requests reach the backend from the frontend container's address. Set `TRUSTED_PROXIES` to that address (or pin a subnet) if you want real client IPs in audit logs. Otherwise the frontend container IP is recorded, which is safe but less informative.

## Health checks

| Endpoint | Use |
|---|---|
| `GET /api/v1/health/live` | Liveness. The process is up |
| `GET /api/v1/health/ready` | Readiness. The DB is reachable **and** the schema is at the latest migration. Returns 503 otherwise |

## Production checklist

- [ ] `APP_ENV=production`, `COOKIE_SECURE=true`, HTTPS termination in front of Next.js
- [ ] Unique `SECRET_ENCRYPTION_KEY` from a secret manager, and backed up
- [ ] Strong `POSTGRES_PASSWORD`. The DB isn't publicly reachable. Automated backups with a tested restore
- [ ] `LOG_FORMAT=json`, logs shipped to central storage
- [ ] `LIVE_TRADING_ENABLED=false` (unchanged until Phase 10 sign-off)
- [ ] Backend and DB not exposed publicly. Only the frontend is

## MT5 hosting (from Phase 2)

The MT5 adapter needs Windows. Either the whole backend runs on a Windows VPS near the broker's servers, or a Windows **MT5 bridge** runs the adapter and the backend stays on Linux. See [BROKERS.md](BROKERS.md).
