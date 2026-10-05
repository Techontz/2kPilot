# Deployment

Single machine (recommended to start): MySQL, Laravel (`php artisan serve` or PHP-FPM behind nginx), the queue worker, the scheduler, the trading engine and `next start`, with only the dashboard exposed over HTTPS.

1. `docker compose up --build` (see `docker-compose.yml`) **or** run the processes under systemd/launchd:
   * `php artisan migrate --force` on each deploy, then the API
   * `php artisan queue:work --tries=1 --timeout=1800`
   * `php artisan schedule:work` (or cron `* * * * * php artisan schedule:run`)
   * `fxrobot serve` (one instance — a database lease prevents two engines from trading)
   * `npm run build && next start` with `BACKEND_URL` set at build time
2. HTTPS in front of Next.js; set `APP_ENV=production`, `APP_DEBUG=false`, `SESSION_SECURE_COOKIE=true`, `FRONTEND_URL`, `SANCTUM_STATEFUL_DOMAINS` and `APP_URL`.
3. Keep the engine and Laravel ports private.
4. Back up MySQL and `BROKER_CREDENTIALS_KEY`.
5. MT5: the bridge runs on Windows near the terminal; connect over Tailscale/WireGuard or HTTPS.

The kill switch starts engaged after a fresh install. LIVE stays locked unless `LIVE_TRADING_ENABLED=true` is set in both services.
