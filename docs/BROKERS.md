# Broker Center

```
2kFX → Broker Manager → Broker Adapter → Broker API / Bridge → Trading Account
```

| Broker | Status | Account types | How it connects |
|---|---|---|---|
| **Paper Trading** | Available | PAPER | Built-in simulator inside the trading engine |
| **Deriv** | Real API integration (needs your Deriv App ID) | DEMO, LIVE | Official Deriv API: REST `api.derivws.com` + OTP-authenticated trading WebSocket |
| **MetaTrader 5** | Available via the Windows bridge | DEMO, LIVE | `mt5_bridge` on a Windows PC/VPS next to a logged-in MT5 terminal |

## Add Broker — 7 steps

1. **Choose broker.**
2. **Demo or Live** — your *expectation*. The broker's own answer is checked in step 5.
3. **Authenticate** — Paper: simulation settings. Deriv: *Sign in with Deriv* or a personal access token. MT5: bridge URL, bridge secret, login, password, server.
4. **Test connection** — the engine connects and asks the broker for the account. Nothing is saved.
5. **Verify account** — account id, Demo/Live **as reported by the broker**, server, currency, balance, equity, instruments by category, trading allowed, order types supported. A mismatch ("you chose DEMO but the broker says LIVE") or an unconfirmed type is refused.
6. **Risk profile** and a name.
7. **Finish** — the connection is tested **again**, saved with **trading OFF**, and connected. It is only shown as CONNECTED after the engine really connected.

Secrets typed in step 3 are encrypted immediately (AES-256-GCM, `BROKER_CREDENTIALS_KEY`) and are never shown again, logged or sent to the browser. Removing an account with trading history archives it and wipes its credentials.

### The account card

Broker · account · PAPER/DEMO/LIVE · CONNECTED/DISCONNECTED/RECONNECTING/ERROR · balance · equity · currency · active strategy · risk profile · **Trading enabled** · last sync. Actions: Sync now, Disconnect/Reconnect, Remove.

## Deriv

2kFX uses the **current official Deriv API** (developers.deriv.com, 2026). The older `ws.derivws.com/websockets/v3?app_id=…` API, the public test app id `1089` and the `oauth.deriv.com` → `acct1/token1` flow have been retired by Deriv and are **not** used.

### What you need from Deriv (once)

1. A Deriv account (a demo account is created automatically when you sign up).
2. A **Deriv App ID**: sign in at **developers.deriv.com → register an application**.
   * For *Sign in with Deriv*, register an **OAuth** app with redirect URI `http://localhost:3421/api/brokers/deriv/oauth/callback` (Deriv allows `http://localhost` for development).
   * For a personal access token, a **PAT** app is enough.
3. Put the App ID in **both** `backend/.env` and `trading-engine/.env`: `DERIV_APP_ID=app12345`, then restart `make dev`.

### Connect

**Brokers → Add broker → Deriv → DEMO →** either

* **Sign in with Deriv** — OAuth 2.0 Authorization Code + PKCE at `auth.deriv.com`. Laravel keeps the `state` and the PKCE verifier in your session, exchanges the code server-side, and keeps the token sealed on the server. Deriv sign-in tokens last about **one hour**: fine for setting up, but a robot that runs 24/7 needs to reconnect, so prefer a token for unattended trading. or
* **Personal access token** — create a token with the **trade** scope in your Deriv account and paste it.

→ **Find my Deriv accounts** (lists your Options accounts: id, demo/real, currency, balance) → choose the one that matches DEMO/LIVE → **Test connection** → verify → risk profile → **Save**.

### How Deriv trades map onto 2kFX

* Trades are Deriv **multiplier** contracts: Buy = `MULTUP`, Sell = `MULTDOWN`. Profit = stake × multiplier × price change ÷ entry price.
* **Volume is in lots**, like MT5: forex 1 lot = 100,000 units, gold/platinum 100, silver 5,000, indices/synthetics/crypto 1. The stake paid = notional ÷ multiplier, rounded down to cents. So risk-profile limits mean the same thing on every broker.
* The **lowest** multiplier the broker allows for a symbol is used (most room for a stop loss, least leverage).
* **Stop loss / take profit** are prices in 2kFX and money amounts at Deriv; the adapter converts. Deriv caps a stop loss at the stake (e.g. ×100 → at most a 1 % price move): a wider stop is refused before anything is sent.
* **No pending orders** at Deriv (shown as "Market orders only"). **No partial closes.**
* **Idempotency:** Deriv does not store a client order id. The engine remembers every intent; after a timeout or restart it matches the contract by symbol, direction and purchase time and never re-sends.
* Account type comes from Deriv (`account_type`: demo → DEMO, real → LIVE). Currency is USD.

### Verified vs not verified

* Verified offline: the adapter against a faithful in-memory Deriv imitation (25 tests), the WebSocket transport against a real local WebSocket server, and the full engine flow (test connection → connect → manual ticket → stop loss hit at the broker → reconciliation). Laravel's OAuth/PKCE flow is tested with Deriv's token endpoint faked.
* **Not verified:** Deriv's live servers — that needs your App ID and token. Nothing in 2kFX claims a Deriv connection works until the connection test against Deriv succeeds.

## MetaTrader 5

See [MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md). Because MetaTrader 5's Python library only runs on Windows, a small bridge runs next to the terminal; the trading engine on your Mac talks to it over HTTPS with HMAC-signed requests and responses.

## Adding another broker

1. `trading-engine/src/fxrobot/broker_engine/adapters/<broker>.py` implementing `BrokerAdapter` (+ `capabilities`).
2. Wire it in `broker_engine/factory.py` and add the connector type (Laravel enum + migration CHECK constraint).
3. Add the catalogue entry in `backend/config/brokers.php` (fields, secret flags).
4. Tests against a fake of the broker's API.

Strategies, the risk engine and the execution engine need **no** change.
