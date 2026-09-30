# Security

Financial software: secure by default. Unsafe production configuration refuses to start.

## Implemented

| Control | Implementation |
|---|---|
| Passwords | Argon2id, rehash on login, constant-work check for unknown users, ≥12 chars with mixed case and a digit |
| Sessions | Opaque 256-bit tokens with only SHA-256 hashes stored. Absolute (12 h) and idle (60 min) expiry. Logout revokes server-side |
| Cookies | `fx_session`: HttpOnly, SameSite=Strict, and Secure in production. `fx_csrf` is echoed in `X-CSRF-Token` for every mutation |
| Authorization | `owner` (everything) and `viewer` (read-only). Every mutating endpoint is owner-only; tested endpoint by endpoint |
| Brute force | Sliding-window limits per email and per IP. 429 with `Retry-After`, and every attempt is audited |
| No self-registration | Users are created with `make user` / `fxrobot create-user` |
| Broker secrets | The MT5 password and bridge secret are Fernet-encrypted (`SECRET_ENCRYPTION_KEY`, rotation via `MultiFernet`). They are **write-only**: never returned by any endpoint, audit entry or notification (tested) |
| Archiving | Removing a connection with history wipes its credentials and keeps its records |
| Bridge channel | HMAC-SHA256 over method, path, timestamp, nonce and body hash. ±30 s window, nonce replay cache. **Signed responses** are verified by the backend. Optional IP allowlist and TLS on the bridge |
| Logging | Keys that look sensitive and inline `password=` / `token:` values are masked. JSON logs carry correlation IDs |
| Audit log | Append-only, enforced by MySQL triggers. Records actor, IP, user agent, correlation ID and outcome, including every denied attempt |
| Errors | Uniform envelope with a correlation ID. No stack traces. Validation errors don't echo submitted values |
| Headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and a CSP with `frame-ancestors 'none'` |
| Same-origin API | The browser never learns the backend address; `BACKEND_URL` is server-side only |
| Client IP | `X-Forwarded-For` is honoured only from `TRUSTED_PROXIES` (uvicorn runs with `--no-proxy-headers`) |
| Production guard | `APP_ENV=production` requires `COOKIE_SECURE=true` and an encryption key; OpenAPI docs are disabled |
| LIVE hard lock | `LIVE_TRADING_ENABLED=false` makes LIVE unreachable. An unknown account environment is treated as real money and never trades |
| Git hygiene | `.env*`, keys, SQLite journals and certificates are ignored |

## Operator checklist

* Use a unique `SECRET_ENCRYPTION_KEY` per environment, keep it in a password manager, and **back it up**.
* Use a dedicated MySQL user with only the privileges listed in [SETUP.md](SETUP.md), not `root`.
* Serve the dashboard only over HTTPS in production, with `COOKIE_SECURE=true`.
* Put the MT5 bridge on a private network (Tailscale or WireGuard) or behind TLS with a firewall rule for the backend IP. Use a long random `BRIDGE_SECRET`.
* Keep `LIVE_TRADING_ENABLED=false` until the live-readiness review is complete ([ROADMAP.md](ROADMAP.md)).

## Known limitations

* No MFA yet. It is a required item on the live-readiness checklist.
* The login rate limiter and the SSE event bus are in-process. Run a single API process, or move them to Redis before scaling out.
* The CSP does not restrict `script-src` yet (nonce-based CSP is planned).
* Any signed-in user, including a viewer, can mark notifications as read. This is intentional, but worth knowing.
