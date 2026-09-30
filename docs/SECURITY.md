# Security

This is financial software. The defaults are secure, and unsafe production configuration refuses to start.

## Implemented

| Control | Implementation |
|---|---|
| Password hashing | Argon2id (`argon2-cffi` defaults), transparent rehash on login, constant-work verification for unknown users |
| Password policy | ≥ 12 characters, mixed case, a digit (`core/security.py`) |
| Sessions | Opaque 256-bit random tokens. Only a SHA-256 hash is stored. Absolute TTL (12 h) and idle timeout (60 min). Logout revokes server-side |
| Cookies | `fx_session`: `HttpOnly; SameSite=Strict; Secure` in production. `fx_csrf` is readable by JS for the header echo |
| CSRF | Per-session token. Every non-GET request must send `X-CSRF-Token`, which is compared against its stored hash in constant time |
| Authorization | Roles `owner` and `viewer`. All trading controls and the audit log are owner-only |
| Brute force | Sliding-window login limiter per email **and** per IP (5 per 15 min by default). 429 with `Retry-After`. Every attempt is audited |
| No self-registration | Users are created with `fxrobot create-user` only |
| Broker secrets | `SecretBox` (Fernet: AES-128-CBC + HMAC-SHA256). Key from `SECRET_ENCRYPTION_KEY`. `MultiFernet` supports rotation. Secrets are write-only through the API (Phase 2) |
| Log masking | Sensitive keys and inline `password=`/`token:` fragments are masked in every log line and in audit details |
| Error responses | Uniform envelope with a correlation ID. No stack traces. Validation errors don't echo submitted values |
| Audit log | Append-only, enforced by a DB trigger. Records actor, IP, user agent, correlation ID and outcome (success/failure/denied) |
| Headers | API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Frontend: plus a CSP with `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` |
| No secrets in the bundle | The backend URL is server-side only (`BACKEND_URL`, not `NEXT_PUBLIC_`). The browser talks same-origin |
| Client IP | `X-Forwarded-For` is honoured only from `TRUSTED_PROXIES` |
| Production guard | `APP_ENV=production` requires `COOKIE_SECURE=true` and an encryption key. The OpenAPI docs are disabled |
| LIVE hard lock | `LIVE_TRADING_ENABLED=false` makes LIVE unreachable, whatever the API or UI does |
| Git hygiene | `.env*` (except examples), keys and `secrets/` are git-ignored |

## Operator responsibilities

* Generate a unique `SECRET_ENCRYPTION_KEY` per environment, store it in a secret manager, and back it up.
* Serve only over HTTPS in production, and set `COOKIE_SECURE=true`.
* Rotate keys by prepending a new key (`new,old`), re-encrypting the stored secrets, then removing the old key.
* Keep `LIVE_TRADING_ENABLED=false` until the Phase 10 live-readiness review has been signed off.

## Known limitations and roadmap

* The login rate limiter is in-process. With several API replicas it must move to Redis.
* The CSP doesn't restrict `script-src` yet. The plan is nonce-based CSP via Next.js proxy.
* No MFA yet. Planned before LIVE is ever unlocked (TOTP for the owner, required for LIVE activation).
* Session listing and "log out other sessions" UI is planned.
