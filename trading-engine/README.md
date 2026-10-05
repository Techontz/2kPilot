# 2kFX trading engine (Python)

The isolated quantitative and broker-facing service: broker adapters (Paper, Deriv, MT5 bridge), Broker Manager, strategies, risk engine, execution engine, reconciliation, paper simulator, backtester. It exposes an internal HTTP API on 127.0.0.1 that only Laravel can call (HMAC-signed), and runs the trading loop.

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env            # then `php artisan fx:keys` in ../backend
.venv/bin/fxrobot serve         # API + trading loop on 127.0.0.1:8431
.venv/bin/pytest                # tests — the schema is built with Laravel's migrations
.venv/bin/ruff check src tests && .venv/bin/mypy
```

The engine never creates database tables: Laravel owns the schema.
