# Deployment

Single machine (recommended to start): MySQL, Redis, Laravel (`php artisan serve` or PHP-FPM behind nginx), Horizon (queue workers), the scheduler, the trading engine and `next start`, with only the dashboard exposed over HTTPS.

1. `docker compose up --build` (see `docker-compose.yml`) **or** run the processes under systemd/launchd:
   * `php artisan migrate --force` on each deploy, then the API
   * create the first admin: `php artisan tp:user --email=… --name=… --role=admin`
   * `php artisan horizon` (queues `default`, `notifications`, `backtests`; run `php artisan horizon:terminate` on deploy so it restarts with new code)
   * `php artisan schedule:work` (or cron `* * * * * php artisan schedule:run`)
   * `fxrobot serve` (one instance — a database lease prevents two engines from trading)
   * `npm run build && next start` with `BACKEND_URL` set at build time
2. HTTPS in front of Next.js; set `APP_ENV=production`, `APP_DEBUG=false`, `SESSION_SECURE_COOKIE=true`, `FRONTEND_URL`, `SANCTUM_STATEFUL_DOMAINS` and `APP_URL`.
3. Keep the engine and Laravel ports private.
4. Keep Redis private (it holds the queues).
5. Back up MySQL and `BROKER_CREDENTIALS_KEY`.
6. Set `TP_REGISTRATION_ENABLED=false` if you don't want public sign-up.
7. Client IPs behind proxies (see below): set `TRUSTED_PROXIES` and make the edge proxy overwrite `X-Forwarded-For`.

## Client IP addresses and proxies

Rate limits (sign-up per IP, the looser per-IP login cap) and the audit log use the client IP. Requests reach Laravel through the Next.js server, so Laravel believes `X-Forwarded-For` only from the proxies in `TRUSTED_PROXIES` (backend `.env`, comma-separated IPs/CIDRs, default `127.0.0.1,::1`):

* **Single machine:** keep the default — Next.js talks to Laravel over loopback.
* **docker compose:** the frontend container reaches the backend over the compose network, so trust that network, e.g. `TRUSTED_PROXIES=172.16.0.0/12` (check yours with `docker network inspect`). Never `*`: any client could then choose its own IP.
* **The edge proxy (nginx) must overwrite the header** with the real client address, never append to what the client sent:

  ```nginx
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header X-Forwarded-Proto $scheme;
  ```

  Next.js appends its own hop when it forwards `/api/*`; the live-updates route (`/api/stream`) does not forward `X-Forwarded-For` at all (its limit is per user).
* Login limits are per **email** first (`TP_LOGIN_ATTEMPTS`, 5 per 15 min), so a shared office or carrier IP cannot lock everyone out; a looser per-IP cap (`TP_LOGIN_ATTEMPTS_PER_IP`, 50 per 15 min) stops spraying many emails from one address. Sign-up is limited per IP (10 per hour): with a wrong `TRUSTED_PROXIES`, all users share the proxy's IP and that budget.

Every new user starts with trading stopped; admins can halt the whole platform (`POST /api/admin/halt`). LIVE stays locked unless `LIVE_TRADING_ENABLED=true` is set in both services.

## Live updates (SSE)

The dashboard listens to `GET /api/stream` (Server-Sent Events) and refetches only what changed: `trading.status`, `account.balance`, `trade.opened`, `trade.closed` and `notification` events, checked every 2 s against the user's own records. If the stream is unavailable the dashboard falls back to polling, so nothing breaks without it — it is only slower.

* **One PHP worker per open tab.** Each connection holds a PHP worker for at most `TP_STREAM_MAX_SECONDS` (default 55 s); the browser then reconnects by itself. Size PHP-FPM `pm.max_children` for *concurrent open dashboard tabs + normal API load* (e.g. 20 tabs + 10 for API requests → at least 30).
* **nginx:** do not buffer the stream — Laravel sends `X-Accel-Buffering: no`; additionally use `proxy_buffering off;` (or `fastcgi_buffering off;`) for `/api/stream`, and set `proxy_read_timeout` / `fastcgi_read_timeout` above 60 s (above `TP_STREAM_MAX_SECONDS`). No gzip on `text/event-stream`.
* **Next.js** must forward `/api/stream` to Laravel without buffering or compressing it (the dashboard's own route handler for `/api/stream`).
* **`php artisan serve`** (development) is a single worker unless started with `PHP_CLI_SERVER_WORKERS=N` **and** `--no-reload` (Laravel ignores the workers setting otherwise); `make dev` does this. With one worker, an open stream blocks every other API request for up to 55 s.
* Rate limit: 30 stream connections per minute per user (`throttle:stream`).
