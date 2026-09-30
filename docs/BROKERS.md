# Brokers

## Principle

Strategies, risk and execution never know which broker they're talking to. They use the `BrokerAdapter` interface (`backend/src/fxrobot/broker_engine/interface.py`) and broker-neutral DTOs (`broker_engine/models.py`). Adding a broker means writing one adapter. Strategy code doesn't change.

A connection type is shown as **available** only when its adapter exists and works on the current host. Nothing is advertised before it works (`broker_engine/registry.py`).

## The interface

| Method | Returns | Notes |
|---|---|---|
| `connect()` / `disconnect()` | — | raises `BrokerConnectionError` |
| `test_connection()` | `AccountInfo` | used by the Add Broker flow |
| `is_connected` | bool | |
| `get_account()` · `get_balance()` · `get_equity()` | `AccountInfo` / `Decimal` | |
| `get_symbols()` · `get_quote(symbol)` | `SymbolInfo[]` / `Quote` | |
| `get_candles(symbol, timeframe, start, end)` | `Candle[]` | closed bars, `[start, end)`, oldest first |
| `get_positions()` · `get_orders()` | `Position[]` / `Order[]` | |
| `place_order(OrderRequest)` | `OrderResult` | see error semantics below |
| `modify_order(id, OrderModification)` · `cancel_order(id)` · `close_position(id, volume?)` | `OrderResult` | |
| `find_order_by_client_id(client_order_id)` | `OrderResult \| None` | **reconciliation hook** |

All methods are `async`. Adapters that wrap blocking SDKs run those calls in a worker thread.

### Error semantics (critical)

| Exception | Meaning | What the caller may do |
|---|---|---|
| `OrderRejectedError` | The broker **definitely refused**, and nothing was executed | Record the rejection. Don't retry blindly |
| `OrderOutcomeUnknownError` | Timeout or dropped link. The order **may have executed** | Call `find_order_by_client_id`, then retry only if it's confirmed absent |
| `BrokerTimeoutError` | A read call timed out | Safe to retry reads |
| `BrokerConnectionError` | Not connected | Reconnect, and pause the account's strategies |

Every `OrderRequest` carries a `client_order_id` (idempotency key). Adapters **must** send it to the broker (for MT5, in the order comment and/or magic-number scheme) so reconciliation is possible.

### Demo vs live detection

`AccountInfo.environment` is `DEMO`, `LIVE` or `UNKNOWN`. **`UNKNOWN` is treated as LIVE** (`AccountEnvironment.is_real_money_possible`). If the system can't prove an account is a demo account, live-trading protections apply.

## MetaTrader 5 (Phase 2)

* **Library:** the official `MetaTrader5` Python package. **It's Windows-only** and talks to a locally installed and running MT5 terminal over IPC.
* **Deployment options:**
  1. Run the backend on a Windows machine or VPS with the MT5 terminal installed. This is the simplest option.
  2. Run a small **MT5 bridge** service on Windows that exposes the `BrokerAdapter` operations over an authenticated local or private network API. The main backend can then stay on Linux or macOS. The adapter interface makes this a drop-in change.
* **Account type:** `account_info().trade_mode`, where `ACCOUNT_TRADE_MODE_DEMO` maps to DEMO and `REAL` maps to LIVE. Anything else maps to UNKNOWN.
* **Credentials:** login, password and server. They're encrypted with `SecretBox` before storage and never returned by the API after saving.
* **Testing:** adapter unit tests use a stub of the `MetaTrader5` module. Integration tests run only on a Windows runner against a **demo** account.

## Adding a new broker

1. Confirm the broker has an official, supported API. Don't scrape or reverse-engineer it.
2. Implement `BrokerAdapter` in `broker_engine/adapters/<name>.py`.
3. Map every broker error onto the error taxonomy above.
4. Add a `ConnectorDescriptor` with honest availability detection.
5. Write contract tests (shared test suite that every adapter must pass) and adapter-specific tests.
