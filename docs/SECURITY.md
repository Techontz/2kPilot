# Security

This is financial software. Defaults are the safe choice.

| Area | Implementation |
|---|---|
| Sign-in | Laravel session auth via Sanctum (first-party cookie, `SameSite=Lax`, HttpOnly, encrypted session payload), session id regenerated on login. No public sign-up: users are created with `php artisan fx:user` (12+ chars, mixed case, a number). |
| MFA | TOTP (RFC 6238) + 8 single-use recovery codes (stored hashed, encrypted). The session is authenticated only **after** the code. Codes can't be replayed. Required to enable LIVE. `FX_REQUIRE_MFA=true` forces enrolment for everyone. |
| CSRF | Laravel's `XSRF-TOKEN` cookie echoed in `X-XSRF-TOKEN` on every state-changing request. |
| Authorization | Policies per model (`app/Policies`): owners change, viewers only read. Gates for global trading controls and the audit log. |
| Rate limiting | Login (5 per email+IP / 15 min; configurable), MFA (5 / 15 min), trading actions (30/min), broker actions (12/min), API (300/min). |
| Validation | Form requests / validator rules for every input; the engine validates again with Pydantic. A stop loss is always required. |
| Broker secrets | AES-256-GCM with `BROKER_CREDENTIALS_KEY` (separate from `APP_KEY`), stored only as ciphertext, decrypted only inside the engine, hidden from every serialisation, never logged, never in frontend bundles. Archiving a broker wipes them. Deriv OAuth tokens never reach the browser. |
| Engine API | Bound to 127.0.0.1, every request HMAC-SHA256-signed over method, path+query, timestamp, nonce and body hash; 60-second window; nonces can't be replayed. |
| Audit log | Append-only (MySQL triggers refuse UPDATE/DELETE). Every security and trading action, allowed or refused, with actor, IP, user agent and masked details. |
| Logs | Secret keys/values masked in Laravel audit details and in engine logs (`password`, `token`, `secret`, `authorization`, …). Request input with secrets is never flashed. |
| Headers | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Cache-Control: no-store` on API responses; CSP `frame-ancestors 'none'` on the dashboard; HSTS over HTTPS. |
| LIVE | `LIVE_TRADING_ENABLED=false` by default in both services. LIVE mode also needs trading stopped, MFA, password and the typed phrase; LIVE accounts can't have trading enabled while locked; UNKNOWN accounts never trade. |
| Configuration | No secrets in Git (`.env` ignored; `.env.example` files contain placeholders). `php artisan fx:keys` generates the shared secrets locally. |

## Operator checklist for production

* `APP_ENV=production`, `APP_DEBUG=false`, HTTPS, `SESSION_SECURE_COOKIE=true`.
* Engine: `APP_ENV=production` refuses to start without a 32+ char `ENGINE_API_SECRET` and a `BROKER_CREDENTIALS_KEY`.
* Back up `BROKER_CREDENTIALS_KEY` — losing it makes stored broker credentials unrecoverable (re-enter them).
* Keep the engine port private (loopback or private network).
