# MT5 Bridge Protocol (v1)

The **MT5 bridge** (`mt5_bridge/`) is a small HTTP service that runs on a **Windows** machine next to the MetaTrader 5 terminal. The 2kFX backend (any OS) talks to it through `fxrobot.broker_engine.adapters.mt5_bridge.MT5BridgeAdapter`.

```
2kFX backend ──HTTPS/HMAC──► mt5_bridge (Windows) ──IPC──► MetaTrader 5 terminal ──► Broker
```

The bridge exposes **only** the operations the broker abstraction needs. It holds no strategy or risk logic.

## Transport

* HTTP/1.1 with JSON bodies (`Content-Type: application/json`, UTF-8).
* Use HTTPS (the bridge supports `--ssl-certfile/--ssl-keyfile`) or a private network (WireGuard, Tailscale, SSH tunnel). Plain HTTP is acceptable only on `127.0.0.1` or inside such a tunnel.
* Base path: `/v1`.
* Request bodies are limited to 64 KiB.

## Authentication (every request, including `/v1/health`)

A shared secret `BRIDGE_SECRET` (≥ 32 characters, random) is configured on both sides. It is used as UTF-8 bytes.

Request headers:

| Header | Value |
|---|---|
| `X-FX-Timestamp` | Unix time in whole seconds (UTC) |
| `X-FX-Nonce` | 32 lowercase hex chars (16 random bytes), unique per request |
| `X-FX-Signature` | lowercase hex `HMAC-SHA256(secret, canonical_request)` |

```
canonical_request = METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + SHA256_HEX(BODY)
```

* `PATH_WITH_QUERY` is exactly as sent, e.g. `/v1/candles?symbol=EURUSD&timeframe=H1&start=...`.
* `BODY` is the raw request body bytes. For an empty body, use `SHA256_HEX(b"")`.

The bridge rejects a request with **401** `unauthorized` when:
* the signature is invalid (compared in constant time), or
* `|now - timestamp| > 30` seconds, or
* the nonce was already seen within the last 120 seconds (replay protection).

**Response signing.** Every response (including errors) carries `X-FX-Signature`:

```
HMAC-SHA256(secret, REQUEST_NONCE + "\n" + STATUS_CODE + "\n" + SHA256_HEX(RESPONSE_BODY))
```

The backend rejects any response whose signature doesn't verify. It treats that as an invalid broker response, and for order submissions as an **unknown outcome**.

Optional: `BRIDGE_ALLOWED_IPS` (comma-separated) restricts the client IPs.

## Data conventions

* Decimal values (prices, volumes, money) are **strings**, e.g. `"1.08512"`. Integers are JSON numbers.
* Timestamps are ISO-8601 **UTC** with `Z`, e.g. `"2026-10-01T13:00:00Z"`. The bridge converts MT5 server time to UTC (see *Time normalization*).
* `side`: `"BUY"` | `"SELL"`. `order_type`: `"MARKET"` | `"LIMIT"` | `"STOP"`.
* Timeframes: `M1 M5 M15 M30 H1 H4 D1`.

## Errors

Non-2xx responses use this body:

```json
{"error": {"code": "market_closed", "message": "Market is closed", "broker_code": "10018"}}
```

| HTTP | `code` | Meaning for the backend |
|---|---|---|
| 401 | `unauthorized` | Bad or missing signature (configuration problem) |
| 422 | `invalid_request` | Malformed parameters |
| 400 | `broker_auth_failed` | MT5 login failed (wrong login, password or server) |
| 503 | `not_connected` | Terminal not initialised, logged out, or lost connection to the trade server |
| 404 | `not_found` | Unknown order, position, or client order ID |
| 404 | `symbol_unavailable` | Symbol doesn't exist or can't be selected in Market Watch |
| 409 | `market_closed` | Trading session closed for the symbol |
| 409 | `insufficient_margin` | Not enough free margin |
| 409 | `rejected` | Broker refused the request (invalid stops, volume, requote…). **Nothing was executed** |
| 504 | `timeout` | A read timed out. Safe to retry |
| 504 | `outcome_unknown` | An order-changing request may or may not have executed. **Reconcile, don't resend** |
| 500 | `internal` | Unexpected bridge error |

## Endpoints

### `GET /v1/health`
```json
{"status": "ok", "bridge_version": "1.0.0",
 "terminal": {"initialized": true, "connected": true, "login": "5012345", "server": "MetaQuotes-Demo",
              "trade_allowed": true, "build": 4410},
 "server_utc_offset_seconds": 10800, "time": "2026-10-01T13:00:05Z"}
```
`status` is `"ok"` even when the terminal is disconnected. The `terminal` object reports the details.

### `POST /v1/session/connect`
Body: `{"login": "5012345", "password": "…", "server": "MetaQuotes-Demo", "terminal_path": null}`
Initialises the terminal if needed, logs in, and returns **AccountInfo**. The password is never logged or stored by the bridge.

### `POST /v1/session/disconnect` → `{"ok": true}`

### `GET /v1/account` → AccountInfo
```json
{"account_id": "5012345", "name": "Conrad", "server": "MetaQuotes-Demo", "currency": "USD",
 "environment": "DEMO", "balance": "10000.00", "equity": "10012.50", "margin": "108.51",
 "free_margin": "9903.99", "margin_level": "9227.07", "leverage": 100, "trade_allowed": true}
```
`environment` comes from `account_info().trade_mode`: `ACCOUNT_TRADE_MODE_DEMO` maps to `"DEMO"` and `ACCOUNT_TRADE_MODE_REAL` maps to `"LIVE"`. Anything else (including CONTEST) maps to `"UNKNOWN"`.

### `GET /v1/symbols` → `[SymbolInfo]`
Only visible and tradeable FX/metal symbols (the ones the terminal reports).
```json
{"name": "EURUSD", "description": "Euro vs US Dollar", "base_currency": "EUR", "quote_currency": "USD",
 "digits": 5, "point": "0.00001", "contract_size": "100000", "volume_min": "0.01", "volume_max": "100",
 "volume_step": "0.01", "trade_allowed": true, "point_value": "1.00"}
```
`point_value` is the value of a one-point move for 1.00 lot in account currency: `trade_tick_value * point / trade_tick_size`.

### `GET /v1/quotes/{symbol}` → `{"symbol": "EURUSD", "bid": "1.08500", "ask": "1.08512", "time": "…Z"}`

### `GET /v1/candles?symbol=EURUSD&timeframe=H1&start=…Z&end=…Z`
**Closed** bars with open time in `[start, end)`, oldest first, at most 50 000.
```json
[{"time": "2026-10-01T12:00:00Z", "open": "1.08410", "high": "1.08530", "low": "1.08390",
  "close": "1.08500", "tick_volume": 3120, "spread_points": 9}]
```
The currently forming bar is never returned.

### `GET /v1/positions` → `[Position]`
```json
{"position_id": "123456789", "symbol": "EURUSD", "side": "BUY", "volume": "0.10",
 "open_price": "1.08500", "open_time": "…Z", "stop_loss": "1.08200", "take_profit": "1.09100",
 "unrealized_pnl": "12.50", "swap": "0.00", "client_order_id": "fx0123456789abcdefghijkl"}
```
`client_order_id` is recovered from the MT5 comment of the position or its opening deal (`null` if absent).

### `GET /v1/orders` → pending `[Order]`
```json
{"order_id": "987", "symbol": "EURUSD", "side": "BUY", "order_type": "LIMIT", "volume": "0.10",
 "status": "PENDING", "price": "1.08000", "stop_loss": "1.07700", "take_profit": "1.08600",
 "created_time": "…Z", "client_order_id": "fx…"}
```

### `GET /v1/deals?start=…Z&end=…Z` → `[Deal]` (trade history)
```json
{"deal_id": "555", "order_id": "987", "position_id": "123456789", "symbol": "EURUSD", "side": "SELL",
 "entry": "OUT", "volume": "0.10", "price": "1.09100", "time": "…Z", "profit": "60.00",
 "commission": "-0.70", "swap": "0.00", "fee": "0.00", "client_order_id": null, "reason": "TP"}
```
`entry`: `IN` | `OUT` | `INOUT`. `reason`: `SL` | `TP` | `SO` (stop-out) | `CLIENT` | `EXPERT` | `OTHER`.

### `GET /v1/orders/lookup/{client_order_id}` → OrderResult, or 404 `not_found`
The **reconciliation** endpoint. It searches the bridge journal, then open positions, pending orders, and recent order and deal history (last 7 days) by comment.

### `POST /v1/orders` → OrderResult
```json
{"client_order_id": "fx0123456789abcdefghijkl", "symbol": "EURUSD", "side": "BUY",
 "order_type": "MARKET", "volume": "0.10", "price": null, "stop_loss": "1.08200",
 "take_profit": "1.09100", "max_slippage_points": 20, "comment": ""}
```
* `client_order_id` is `^[a-z0-9]{8,24}$`. It is written to the MT5 order comment (MT5 limit: 31 characters).
* **Idempotent.** If the bridge has seen this `client_order_id` before, it returns the stored result and **does not send again**. If a previous attempt is in flight or its result was lost, the bridge first looks the order up in MT5. If it still can't tell, it returns 504 `outcome_unknown`.
* Market orders use the current ask (BUY) or bid (SELL) with `deviation = max_slippage_points`. The filling mode comes from the symbol's `filling_mode` (FOK, then IOC, then RETURN).

OrderResult:
```json
{"client_order_id": "fx…", "status": "FILLED", "broker_order_id": "987", "broker_position_id": "123456789",
 "filled_volume": "0.10", "fill_price": "1.08512", "broker_code": "10009", "broker_message": "Request completed"}
```
`status`: `FILLED` | `PARTIALLY_FILLED` | `PENDING` | `CANCELLED` | `REJECTED`. A retcode that means the broker refused the request is returned as a **409 `rejected`** error. Retcodes mean:

| MT5 retcode | Result |
|---|---|
| 10009 DONE | `FILLED` |
| 10008 PLACED | `PENDING` |
| 10010 DONE_PARTIAL | `PARTIALLY_FILLED` |
| 10019 NO_MONEY | 409 `insufficient_margin` |
| 10018 MARKET_CLOSED | 409 `market_closed` |
| 10012 TIMEOUT, `order_send` returned `None`, or connection lost mid-request | 504 `outcome_unknown` |
| any other | 409 `rejected` with `broker_code` |

### `POST /v1/orders/{order_id}/modify` — body `{"price", "stop_loss", "take_profit"}` → OrderResult
### `POST /v1/orders/{order_id}/cancel` → OrderResult (`CANCELLED`)
### `POST /v1/positions/{position_id}/modify` — body `{"stop_loss", "take_profit"}` → OrderResult
### `POST /v1/positions/{position_id}/close` — body `{"client_order_id", "volume"}` → OrderResult
`volume: null` closes the whole position. Idempotent by `client_order_id`, like `POST /v1/orders`.

## Time normalization

MT5 reports bar and tick times in **trade-server time** (often UTC+2/UTC+3 with DST), encoded as if they were UTC. The bridge converts every outgoing time to real UTC:

* `BROKER_SERVER_UTC_OFFSET=auto` (default): offset = `round((last_tick_time − utc_now) / 1800) × 1800`, measured on a liquid symbol while its market is open and re-measured hourly. If the market is closed and no offset is known yet, candle and deal endpoints return 503 `not_connected` with the message `server time offset unknown`.
* `BROKER_SERVER_UTC_OFFSET=+3` (hours) forces a fixed offset.

## Concurrency

The `MetaTrader5` Python package is not thread-safe. The bridge serialises every terminal call on one worker thread, with per-call timeouts: 10 s for reads, 30 s for trade requests.
