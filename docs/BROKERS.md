# Broker Center

```
2kPilot → Broker Manager → Broker Adapter → Broker API → Trading Account
```

| Broker | Status | Account types | How it connects |
|---|---|---|---|
| **Paper Trading** | Available | PAPER | Built-in simulator inside the trading engine |
| **Deriv** | Real API integration (needs your Deriv App ID) | DEMO, LIVE | Official Deriv API: REST `api.derivws.com` + OTP-authenticated trading WebSocket |

## Add Broker — 7 steps

1. **Choose broker.**
2. **Demo or Live** — your *expectation*. The broker's own answer is checked in step 5.
3. **Authenticate** — Paper: simulation settings. Deriv: *Sign in with Deriv* or a personal access token.
4. **Test connection** — the engine connects and asks the broker for the account. Nothing is saved.
5. **Verify account** — account id, Demo/Live **as reported by the broker**, server, currency, balance, equity, instruments by category, trading allowed, order types supported. A mismatch ("you chose DEMO but the broker says LIVE") or an unconfirmed type is refused.
6. **Risk profile** and a name.
7. **Finish** — the connection is tested **again**, saved with **trading OFF**, and connected. It is only shown as CONNECTED after the engine really connected.

Secrets typed in step 3 are encrypted immediately (AES-256-GCM, `BROKER_CREDENTIALS_KEY`) and are never shown again, logged or sent to the browser. Removing an account with trading history archives it and wipes its credentials. Every connection and account belongs to the user who added it; nobody else sees or trades it.

### The account card

Broker · account · PAPER/DEMO/LIVE · CONNECTED/DISCONNECTED/RECONNECTING/ERROR · balance · equity · currency · active strategy · risk profile · **Trading enabled** · last sync. Actions: Sync now, Disconnect/Reconnect, Remove.

## Deriv

2kPilot uses the **current official Deriv API** (developers.deriv.com, 2026). The older `ws.derivws.com/websockets/v3?app_id=…` API, the public test app id `1089` and the `oauth.deriv.com` → `acct1/token1` flow have been retired by Deriv and are **not** used.

### What you need from Deriv (once)

1. A Deriv account (a demo account is created automatically when you sign up).
2. A **Deriv App ID**: sign in at **developers.deriv.com → register an application**.
   * For *Sign in with Deriv*, register an **OAuth** app with redirect URI `http://localhost:3421/api/brokers/deriv/oauth/callback` (Deriv allows `http://localhost` for development).
     The registered redirect URI must be **exactly** `DERIV_OAUTH_REDIRECT_URL` (same host and port as the dashboard you open, e.g. `:3421`, or `:3001` if you run Next there), and it should be the app's only redirect URI during development.
     Deriv's web firewall answers **403 "Access Denied | WAF"** to any sign-in or token request whose `redirect_uri` points at a loopback host (`localhost`, `127.0.0.1`, `::1`), so for those 2kPilot leaves `redirect_uri` out of both requests and Deriv uses the registered one. Public `https://` redirect URLs are always sent explicitly.
     The return URL (`GET /api/brokers/deriv/oauth/callback`) is served through Laravel's **web** session, not Sanctum: it is a top-level redirect from Deriv whose `Referer` is Deriv's, so Sanctum's "is this the dashboard?" check would ignore the session cookie. If the 2kPilot session ended meanwhile, the user is sent back to the wizard with `?deriv=signed_out`.
   * For a personal access token, a **PAT** app is enough.
3. Put the App ID in **both** `backend/.env` and `trading-engine/.env`: `DERIV_APP_ID=app12345`, then restart `make dev`.

### Connect

**Brokers → Add broker → Deriv → DEMO →** either

* **Sign in with Deriv** — OAuth 2.0 Authorization Code + PKCE at `auth.deriv.com`. Laravel keeps the `state` and the PKCE verifier in your session, exchanges the code server-side, and keeps the token sealed on the server. Deriv sign-in tokens last about **one hour**: fine for setting up, but a robot that runs 24/7 needs to reconnect, so prefer a token for unattended trading. or
* **Personal access token** — create a token with the **trade** scope in your Deriv account and paste it.

→ **Find my Deriv accounts** (lists your Options accounts: id, demo/real, currency, balance) → choose the one that matches DEMO/LIVE → **Test connection** → verify → risk profile → **Save**.

### How Deriv trades map onto 2kPilot: contracts and stakes

Deriv Options are **contracts bought for a stake**, not lots. Strategies still say BUY or SELL; the **contract spec** on each strategy assignment (and on backtests and manual tickets) decides what is bought:

| Family | BUY | SELL | Parameters | Most it can lose |
|---|---|---|---|---|
| `RISE_FALL` | `CALL` (`CALLE` with *allow equals*) | `PUT` (`PUTE`) | `duration` + `duration_unit` (`t` ticks, `s`, `m`, `h`, `d`), optional `stake` | the stake |
| `MULTIPLIER` | `MULTUP` | `MULTDOWN` | `multiplier`, optional `take_profit_amount` / `stop_loss_amount` (money), optional `stake` | the stake (Deriv stops the contract out first) |
| `SPOT` | long | short | lots + stop-loss/take-profit prices | — **Paper only**; refused on Deriv |

* **Default** for a new Deriv assignment: Rise/Fall, **5 minutes**, no *allow equals*. Five minutes rather than five ticks because strategies decide on closed candles: a tick contract would settle before the next candle could show whether the idea worked.
* **Stake**: the assignment's own `stake`, otherwise the risk profile's `stake_amount` (Beginner: 1.00). `volume` is 1 (one contract).
* **Before buying**, the risk engine checks the contract against the broker's offer (`contracts_for`) and prices it (`proposal`) to read the stake limits — see [RISK_ENGINE.md](RISK_ENGINE.md).

#### Exact API usage (developers.deriv.com, 2026 schemas)

| Step | Request | Fields used from the reply |
|---|---|---|
| Instruments & market status | `{"active_symbols": "brief"}` (no contract filter) | `underlying_symbol`, `underlying_symbol_name`, `market`, `pip_size`, `exchange_is_open`, `is_trading_suspended` |
| What is offered | `{"contracts_for": "<symbol>"}` (cached 10 min per symbol) | `available[].contract_type`, `min_contract_duration` / `max_contract_duration` (strings like `"1t"`, `"15s"`, `"1d"`, parsed), `expiry_type`, `barriers`, `multiplier_range` |
| Price a Rise/Fall | `{"proposal":1, "contract_type":"CALL", "underlying_symbol":…, "basis":"stake", "amount":…, "currency":…, "duration":5, "duration_unit":"m"}` | `id`, `ask_price`, `payout`, `spot`, `longcode`, `validation_params.stake.min/max` |
| Price a Multiplier | same with `"multiplier": N` and optional `"limit_order": {"take_profit": x, "stop_loss": y}` | as above |
| Buy | `{"buy": <proposal id>, "price": <ask_price>}` | `contract_id`, `buy_price`, `payout`, `transaction_id`, `start_time`, `longcode` |
| Track / settle | `{"proposal_open_contract":1, "subscribe":1}` (all open contracts) and `{"proposal_open_contract":1, "contract_id":…}` | `status` (open/won/lost/sold), `is_sold`, `is_valid_to_sell`, `entry_spot`, `exit_spot`, `date_expiry`, `buy_price`, `payout`, `profit`, `bid_price`, `commission`, `limit_order.*.value` |
| Close early | `{"sell": <contract_id>, "price": 0}` — only when `is_valid_to_sell` = 1 | `sold_for`, `transaction_id` |
| History | `{"profit_table":1, …, "contract_type":[all six]}` | `contract_id`, `buy_price`, `sell_price`, `payout`, `purchase_time`, `sell_time` |
| Candles | `{"ticks_history": <symbol>, "style":"candles", "granularity":…, "start", "end"}` | `candles[]` — public market data, used for strategies and dataset downloads (e.g. R_10 … R_100, 1HZ100V) |

* **Money fields of `proposal_open_contract` are strings** and are parsed as `Decimal` (never float); spots are `entry_spot` / `exit_spot`.
* **Never pay more than the stake**: the buy is refused when `ask_price` > stake + 0.01 (rounding). The buy is sent with `price` = the quoted ask, so Deriv refuses it if the price moved up.
* **Payouts** are whatever each proposal says (`payout ÷ ask_price`), and an app markup of up to 3 % reduces them. Rise/Fall P/L: won → payout − stake; lost → −stake. CALL wins if exit spot > entry spot (CALLE ≥), PUT if exit < entry (PUTE ≤); **equal spots lose CALL/PUT**.
* **Multipliers**: profit ≈ stake × multiplier × price change ÷ entry − commission. Configured money amounts are sent as `limit_order`; otherwise the strategy's stop/target prices are converted (amount = stake × multiplier × |level − entry| ÷ entry). A converted stop further than the stake is left out: Deriv's stop out closes the contract first, so the loss is bounded by the stake either way. The commission reported on the open contract is recorded as the trade's `fees` (Deriv prices already include it, so it is not deducted twice). Stop loss / take profit can still be edited on open Multipliers (`contract_update`).
* **Settlement**: a Rise/Fall settles at expiry at Deriv, with no action from us. The engine sees it through the open-contract stream, or — if it was offline — through `profit_table` + `proposal_open_contract` by contract id, and closes the trade with `exit_spot`, `outcome` (WON/LOST/SOLD) and P/L. A contract we saw settle (its sold `proposal_open_contract`, with `sell_price`) but that `profit_table` does not list yet is reported from those details. If neither has it, the trade is closed with its P/L pending and re-read every 30 s; meanwhile new entries on the account are blocked. A rate-limited per-contract lookup fails the whole history read (retried next tick) instead of recording entry/exit 0 or guessing the exit reason.
* **Early close**: allowed only when Deriv says `is_valid_to_sell`; otherwise the dashboard is told "This contract settles at expiry".
* **No pending orders. No partial closes.**
* **Idempotency**: Deriv does not store a client order id. The engine remembers every intent; after a timeout or restart it matches the contract by symbol, **exact contract type**, stake and purchase time — among open contracts first, then among settled ones — and never buys again. Contracts the database already ties to another order/trade of the account are never matched (the adapter's own claims are lost on restart); among several candidates the one whose stake and purchase time fit best wins.
* **Reconciliation of uncertain orders**: once Deriv acknowledged a buy or sell (a receipt with a contract id), nothing afterwards can turn it into "not executed" — a failed detail fetch just leaves the details to the next sync. An order whose outcome is UNKNOWN is concluded "not executed" only when `portfolio` **and** `profit_table` were both read successfully for its window and the 2-minute grace period has passed; a failed read keeps it UNKNOWN. Each UNKNOWN order is looked up at most every 15 s, and one portfolio + profit_table read (reused for 10 s, always taken after the portfolio it complements) serves every order reconciled together, to stay inside the 30/min budget.
* **Rate limits** (per connection, client-side): proposal + proposal_open_contract + buy + sell 360/min and 14,400/h; balance + statement 100/min, 2,000/h; portfolio + profit_table 30/min, 1,500/h; everything else 220/min, 14,400/h; ping is free. A request that would break a budget waits up to 2 s and is otherwise refused **before it is sent** — a refused buy never executed.
* Account type comes from Deriv (`account_type`: demo → DEMO, real → LIVE).

**Checked against Deriv's public API (unauthenticated `…/ws/public`, 2026-10-11; read-only: `contracts_for`, a price quote, `ticks_history` — nothing bought):**

| | R_10 (Volatility 10 Index) | R_25 (Volatility 25 Index) |
|---|---|---|
| Multipliers (`multiplier_range`) | 400, 1000, 2000, 3000, 4000 | 160, 400, 800, 1200, 1600 |
| Stake (`validation_params.stake`, USD) | 1.00 – 500.00 | 1.00 – 500.00 |
| Stop loss / take profit amounts (1.00 stake) | 0.10 – 1.00 / 0.10 – 50.00 | 0.10 – 1.00 / 0.10 – 50.00 |
| Commission (proposal, 1.00 stake, lowest multiplier) | 0.02 (≈ 0.005 % of stake × 400) | 0.02 (≈ 0.0125 % of stake × 160) |
| Rise/Fall | CALL/PUT, 15 s – 1 d intraday | same |
| Pip size, hours | 0.001, open 24/7 | 0.001, open 24/7 |

The stop loss and stop out apply to the profit **net of commission** (the quoted barriers for a 0.30 stop and the 1.00 stop out match stake × multiplier × move − 0.02). The adapter now reads `validation_params.stop_loss` / `take_profit` into the stake quote, and the risk engine refuses amounts outside that range before buying. Candle history: see [BACKTESTING.md](BACKTESTING.md#data) (end-only paging, about one year).

`GET /api/markets/contracts?account_id=&symbol=` shows what a symbol offers (families, duration ranges, multipliers, default contract), from the engine's cached `contracts_for`.

### The Paper price feed

Paper accounts (price source *synthetic*) run on a deterministic **1-minute feed** (`trading-engine/src/fxrobot/market_data/synthetic_feed.py`): every 1-minute bar is a pure function of (seed, symbol, time), so prices never change after an engine restart and do not depend on today's date. Every timeframe a strategy can use — M1, M5, M15, M30, H1, H4, D1 — is aggregated from those same minutes, and quotes, SL/TP checks and Rise/Fall settlement read them too. Forex symbols close from Friday 21:00 to Sunday 21:00 UTC; `R_10 … R_100` trade around the clock.

* **Speed.** *Simulation speed* is wall-clock seconds per 15 simulated minutes (default 2 s). The simulation starts *Start the simulation this many days ago* (default 30) in the past and fast-forwards, but never runs ahead of real time; once it catches up it follows the real clock.
* **Every candle is evaluated.** While fast-forwarding, the engine stops each advance at the next close of the finest timeframe an active strategy decides on (one M5 candle per tick for an M5 strategy), so no candle is skipped.
* *Practice data* for backtests comes from the same feed: with the same seed (42 by default) a practice dataset holds exactly the prices a Paper account trades.
* *Replay* connections replay a stored dataset at its own timeframe; strategies on shorter candles cannot run on them.

### Paper contracts (simulated)

Paper accounts trade SPOT **and** simulated Rise/Fall and Multipliers on the paper price feed — so the Rise/Fall flow can be rehearsed without a broker:

* Rise/Fall payout: profit = stake × `rise_fall_payout_ratio` (paper connection setting, default **0.95**, labelled *simulated*). Settlement at expiry compares the exit price (close of the first simulated bar at or after expiry) with the entry; equal prices lose CALL/PUT and win CALLE/PUTE. Tick durations count simulated 1-minute bars as ticks; durations shorter than one minute are refused. Paper Rise/Fall cannot be sold early.
* Multipliers: the formula above, TP/SL checked on each bar's high/low (stop first), optional `multiplier_commission_pct` (default 0), loss capped at the stake.
* `R_10 … R_100` are available as SYNTHETIC 24/7 instruments (2kPilot's generator imitating the *shape* of volatility indices — not Deriv data).

### Verified vs not verified

* Verified offline: the adapter against a faithful in-memory Deriv imitation (48 tests: Rise/Fall and Multiplier buys, settlement from string money fields, `is_valid_to_sell`, settled-while-offline reconciliation, link drops after a buy/sell receipt, failed history reads, rate limits), the WebSocket transport against a real local WebSocket server, and the full engine flow (test connection → connect → manual tickets → settlement at the broker → reconciliation, history download). Laravel's OAuth/PKCE flow is tested with Deriv's token endpoint faked.
* **Not verified** (handled defensively; needs your App ID and a demo account):
  * Deriv's live servers in general.
  * How `contracts_for` groups Rise/Fall: historically category `callput` — we match on contract type `CALL`/`PUT` **without a barrier** (with a barrier they are Higher/Lower).
  * Typical payouts (~1.9–1.95× for at-the-money Rise/Fall on volatility indices) and the minimum stake (often quoted as 0.35 USD) — both are read from each proposal, never hard-coded; missing stake limits make the trade fail closed.
  * The `status` value of a Multiplier closed by take profit / stop loss (we classify by exit reason and P/L sign), and whether `profit_table` money fields are numbers or strings (both are parsed).
  * Whether OAuth tokens can be refreshed (no refresh token is documented).

## Adding another broker

1. `trading-engine/src/fxrobot/broker_engine/adapters/<broker>.py` implementing `BrokerAdapter` (+ `capabilities`).
2. Wire it in `broker_engine/factory.py` and add the connector type (Laravel enum + migration CHECK constraint).
3. Add the catalogue entry in `backend/config/brokers.php` (fields, secret flags).
4. Tests against a fake of the broker's API.

Strategies, the risk engine and the execution engine need **no** change.
