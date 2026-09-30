# Brokers

Strategies, risk and execution never know which broker they talk to. They use the `BrokerAdapter` contract (`broker_engine/interface.py`) and broker-neutral DTOs. Adding a broker means writing one adapter.

## Connection types

| Connector | Status | Environments | Notes |
|---|---|---|---|
| **Paper / Simulation** (`paper`) | Implemented | PAPER | In-process simulator. SYNTHETIC prices or replay of stored data |
| **MetaTrader 5** (`mt5_bridge`) | Implemented | DEMO, LIVE | Needs the Windows bridge ([setup](MT5_BRIDGE_SETUP.md)). The UI shows *not connected* until the bridge and terminal really answer |

A connection is never shown as CONNECTED unless the adapter actually connected.

## The adapter contract (synchronous)

`connect()`, `disconnect()`, `test_connection()`, `is_connected`, `health()`, `now()`, `advance()`, `get_account()`, `get_balance()`, `get_equity()`, `get_symbols()`, `get_symbol()`, `get_quote()`, `get_candles()` (closed bars, `[start, end)`), `get_positions()`, `get_orders()`, `get_deals()` (trade history), `find_order_by_client_id()` (reconciliation), `place_order()`, `modify_order()`, `modify_position()`, `close_position()`, `cancel_order()`.

### Error taxonomy (the safety-critical part)

| Error | Meaning | What the system does |
|---|---|---|
| `OrderRejectedError` (+ `MarketClosedError`, `InsufficientMarginError`) | The broker **definitely refused**; nothing executed | Order REJECTED, signal FAILED, notification |
| `BrokerConnectionError` | Not connected; the request was not sent | Order FAILED ("Not sent"), reconnect with backoff |
| `OrderOutcomeUnknownError` | Timeout / dropped link / unverifiable reply during a trade call | Order **UNKNOWN**. Reconcile via `find_order_by_client_id`. **Never resent.** The account takes no new entries until resolved |
| `BrokerTimeoutError` | A read timed out | Safe to retry reads |
| `BrokerAuthError` | Credentials or bridge secret refused | ERROR status, long backoff (no hammering) |
| `InvalidBrokerResponseError` | Malformed or untrusted data | Treated as a failure; for trades, as UNKNOWN |

Every order carries a 24-character `client_order_id` (`fx` + base32). It is persisted **before** the call and sent to the broker. On MT5 it becomes the order comment.

### Environment verification

`AccountInfo.environment` comes from the broker. **UNKNOWN is treated as real money** and can never trade. The wizard refuses to save an account whose broker-reported type differs from what you selected.

## Connection lifecycle (`BrokerManager`)

* One adapter per connection (the paper simulator keeps state).
* Lazy connect. Reconnect with exponential backoff (2 s … 60 s); credential failures back off for 60 s.
* Status transitions (CONNECTED / DISCONNECTED / RECONNECTING / ERROR) are persisted and raise notifications (connected, disconnected, reconnected, error).
* A health probe runs at most every 10 s per connection.
* Paper state is persisted immediately after any trade action, and throttled for pure price movement.

## Removing a connection

Accounts with open positions cannot be removed. A connection whose accounts have **any** history is **archived**: disabled, trading off, credentials wiped. Journals and analytics keep every record. Only connections without history are deleted.

## Paper / Simulation broker

| Behaviour | Model |
|---|---|
| Market fills | Ask (buy) / bid (sell) plus the configured adverse slippage |
| Costs | Commission per lot per side (default 3.5 USD); spread from the simulated bar (wider at the 21:00 UTC rollover) |
| Margin | Notional ÷ leverage; stop-out at a 50 % margin level (worst position first) |
| SL / TP | Checked on every completed 15-minute bar. **Stop wins** if a bar touches both; gaps fill at the (worse) open |
| Pending orders | LIMIT/STOP triggered on the correct side of the spread; a stop hit in the same bar applies immediately |
| Idempotency | Repeated client IDs return the stored result; a client ID can't be reused for a different action |
| Time | Starts *N days ago*, accelerated by *seconds per bar*, **never ahead of real time**; the market is closed at weekends |
| Faults (tests) | Simulated disconnect, lost response after execution, timeout before execution |

Use `seconds_per_bar ≥ ENGINE_TICK_SECONDS / 2` so every closed bar is evaluated while still fresh. The default `2` with a 2 s tick is ideal. Faster settings make the risk engine reject stale signals, which is correct behaviour.

## MetaTrader 5

See [MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md) (install) and [MT5_BRIDGE_PROTOCOL.md](MT5_BRIDGE_PROTOCOL.md) (wire protocol). The backend client (`adapters/mt5_bridge.py`):
* signs every request (HMAC-SHA256, timestamp, nonce) and **verifies every response signature**;
* parses strictly (malformed → `InvalidBrokerResponseError`, or UNKNOWN on trades);
* maps bridge error codes onto the taxonomy above;
* is tested against the real bridge app with a fake MT5 module (`tests/test_mt5_bridge_contract.py`).

## Adding a broker

1. Confirm the broker has an official, supported API.
2. Implement `BrokerAdapter` in `broker_engine/adapters/<name>.py`, mapping every error onto the taxonomy.
3. Add a `ConnectorDescriptor` in `registry.py` and a builder in `factory.py`.
4. Write tests for the contract, the error mapping and reconciliation.
