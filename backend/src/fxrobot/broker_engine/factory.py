"""Build adapter instances from stored connection configuration."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.mt5_bridge import MT5BridgeAdapter
from fxrobot.broker_engine.adapters.paper import FaultInjector, PaperBroker, PaperConfig
from fxrobot.broker_engine.adapters.paper_market import ReplayMarket, SimMarket, SyntheticMarket
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.core.crypto import SecretBox
from fxrobot.domain.market import Timeframe
from fxrobot.domain.trading import ConnectorType
from fxrobot.market_data import store
from fxrobot.market_data.synthetic import DEFAULT_SPECS
from fxrobot.models import BrokerConnection, Dataset, PaperState


class ConfigurationError(ValueError):
    """Stored/submitted connection settings are invalid."""


def parse_symbols(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    symbols = [s.strip().upper() for s in items if str(s).strip()]
    if not symbols:
        raise ConfigurationError("At least one symbol is required")
    return list(dict.fromkeys(symbols))


def normalize_paper_settings(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("price_source", "synthetic")
    if source not in ("synthetic", "replay"):
        raise ConfigurationError("price_source must be 'synthetic' or 'replay'")
    try:
        settings = {
            "price_source": source,
            "symbols": parse_symbols(raw.get("symbols", "EURUSD,GBPUSD,USDJPY")),
            "initial_balance": str(Decimal(str(raw.get("initial_balance", "10000")))),
            "currency": str(raw.get("currency", "USD")).upper(),
            "leverage": int(raw.get("leverage", 100)),
            "seconds_per_bar": float(raw.get("seconds_per_bar", 2)),
            "start_days_ago": int(raw.get("start_days_ago", 30)),
            "commission_per_lot": str(Decimal(str(raw.get("commission_per_lot", "3.5")))),
            "slippage_points": int(raw.get("slippage_points", 0)),
            "seed": int(raw.get("seed", 42)),
            "dataset_symbol_map": dict(raw.get("dataset_symbol_map") or {}),
        }
    except (ValueError, ArithmeticError) as exc:
        raise ConfigurationError(f"Invalid paper settings: {exc}") from exc
    if Decimal(settings["initial_balance"]) <= 0:
        raise ConfigurationError("Starting balance must be positive")
    if not 1 <= settings["leverage"] <= 1000:
        raise ConfigurationError("Leverage must be between 1 and 1000")
    if settings["currency"] != "USD":
        raise ConfigurationError("Paper accounts currently support USD only")
    if not 0 <= settings["seconds_per_bar"] <= 3600:
        raise ConfigurationError("seconds_per_bar must be between 0 and 3600")
    if source == "synthetic":
        unknown = [s for s in settings["symbols"] if s not in DEFAULT_SPECS]
        if unknown:
            raise ConfigurationError(f"No synthetic data for: {', '.join(unknown)}")
    elif not settings["dataset_symbol_map"]:
        raise ConfigurationError("Replay needs at least one dataset")
    return settings


def normalize_mt5_settings(raw: dict[str, Any]) -> dict[str, Any]:
    url = str(raw.get("bridge_url", "")).strip()
    if not url.startswith(("http://", "https://")):
        raise ConfigurationError("Bridge URL must start with http:// or https://")
    login = str(raw.get("login", "")).strip()
    server = str(raw.get("server", "")).strip()
    if not login.isdigit():
        raise ConfigurationError("MT5 account number must be numeric")
    if not server:
        raise ConfigurationError("MT5 server is required")
    verify = raw.get("verify_tls", True)
    verify_bool = str(verify).lower() not in ("false", "0", "no")
    return {
        "bridge_url": url.rstrip("/"),
        "login": login,
        "server": server,
        "verify_tls": verify_bool,
    }


def build_market(db: Session, settings: dict[str, Any], now: datetime | None = None) -> SimMarket:
    now = now or datetime.now(UTC)
    start = now - timedelta(days=settings.get("start_days_ago", 30))
    if settings["price_source"] == "synthetic":
        return SyntheticMarket(
            seed=settings["seed"],
            symbols=settings["symbols"],
            start=start,
            seconds_per_bar=settings["seconds_per_bar"],
        )
    bars, specs, timeframes = {}, {}, set()
    for symbol, dataset_id in settings["dataset_symbol_map"].items():
        dataset = db.get(Dataset, _uuid(dataset_id))
        if dataset is None:
            raise ConfigurationError(f"Dataset for {symbol} no longer exists")
        timeframes.add(dataset.timeframe)
        bars[symbol] = store.load_candles(db, dataset.id)
        spec = DEFAULT_SPECS.get(symbol)
        if spec is None:
            raise ConfigurationError(f"Replay supports FX majors only; {symbol} unknown")
        specs[symbol] = spec.symbol_info()
    if len(timeframes) != 1:
        raise ConfigurationError("All replay datasets must share one timeframe")
    base_tf: Timeframe = timeframes.pop()
    first = min((b[0].time for b in bars.values() if b), default=start)
    replay_start = first + timedelta(days=60)  # warm-up history for indicators
    return ReplayMarket(
        bars=bars,
        specs=specs,
        base_timeframe=base_tf,
        start=replay_start,
        seconds_per_bar=settings["seconds_per_bar"],
    )


def build_adapter(
    db: Session,
    connection: BrokerConnection,
    secret_box: SecretBox | None,
    *,
    on_paper_change: Callable[[dict[str, Any], bool], None] | None = None,
    faults: FaultInjector | None = None,
) -> BrokerAdapter:
    if connection.connector_type is ConnectorType.PAPER:
        settings = normalize_paper_settings(connection.settings)
        market = build_market(db, settings)
        state_row = db.get(PaperState, connection.id)
        config = PaperConfig(
            account_id=f"PAPER-{str(connection.id)[:8].upper()}",
            currency=settings["currency"],
            initial_balance=Decimal(settings["initial_balance"]),
            leverage=settings["leverage"],
            commission_per_lot=Decimal(settings["commission_per_lot"]),
            slippage_points=settings["slippage_points"],
        )
        return PaperBroker(
            market,
            config,
            state=state_row.state if state_row else None,
            on_change=on_paper_change,
            faults=faults,
        )
    if connection.connector_type is ConnectorType.MT5_BRIDGE:
        if secret_box is None:
            raise ConfigurationError("SECRET_ENCRYPTION_KEY is not configured on the server")
        if not connection.credentials_encrypted:
            raise ConfigurationError("Connection has no stored credentials")
        secrets = json.loads(secret_box.decrypt(connection.credentials_encrypted))
        settings = normalize_mt5_settings(connection.settings)
        return mt5_from(settings, secrets)
    raise ConfigurationError(f"Unsupported connector {connection.connector_type}")


def mt5_from(settings: dict[str, Any], secrets: dict[str, Any]) -> MT5BridgeAdapter:
    try:
        return MT5BridgeAdapter(
            base_url=settings["bridge_url"],
            secret=str(secrets.get("bridge_secret", "")),
            login=settings["login"],
            password=str(secrets.get("password", "")),
            server=settings["server"],
            verify_tls=settings["verify_tls"],
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def _uuid(value: Any) -> Any:
    import uuid

    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
