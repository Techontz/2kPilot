"""Build adapter instances from stored connection configuration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.deriv import DerivAdapter
from fxrobot.broker_engine.adapters.paper import FaultInjector, PaperBroker, PaperConfig
from fxrobot.broker_engine.adapters.paper_market import (
    ReplayMarket,
    SimMarket,
    SyntheticMarket,
    paper_clock,
)
from fxrobot.broker_engine.errors import BrokerAuthError as BrokerAuthErrorType
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.core.crypto import SecretBox, SecretBoxError
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
            # Simulated contracts: profit per 1 of stake when a Rise/Fall wins.
            "rise_fall_payout_ratio": str(Decimal(str(raw.get("rise_fall_payout_ratio", "0.95")))),
            "multiplier_commission_pct": str(
                Decimal(str(raw.get("multiplier_commission_pct", "0")))
            ),
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
    if not Decimal("0.01") <= Decimal(settings["rise_fall_payout_ratio"]) <= Decimal(2):
        raise ConfigurationError("rise_fall_payout_ratio must be between 0.01 and 2")
    if not Decimal(0) <= Decimal(settings["multiplier_commission_pct"]) <= Decimal(10):
        raise ConfigurationError("multiplier_commission_pct must be between 0 and 10")
    if not 0 <= settings["seconds_per_bar"] <= 3600:
        raise ConfigurationError("seconds_per_bar must be between 0 and 3600")
    if source == "synthetic":
        unknown = [s for s in settings["symbols"] if s not in DEFAULT_SPECS]
        if unknown:
            raise ConfigurationError(f"No synthetic data for: {', '.join(unknown)}")
    elif not settings["dataset_symbol_map"]:
        raise ConfigurationError("Replay needs at least one dataset")
    return settings


def normalize_deriv_settings(raw: dict[str, Any]) -> dict[str, Any]:
    account_id = str(raw.get("account_id", "")).strip().upper()
    if not account_id or not account_id.replace("_", "").isalnum() or len(account_id) > 32:
        raise ConfigurationError("Choose a Deriv account")
    multiplier = raw.get("multiplier")
    if multiplier in (None, "", "lowest"):
        multiplier_value = None
    else:
        try:
            multiplier_value = int(multiplier)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("Multiplier must be a whole number") from exc
        if not 1 <= multiplier_value <= 5000:
            raise ConfigurationError("Multiplier is out of range")
    return {"account_id": account_id, "multiplier": multiplier_value}


def normalize_settings(connector: ConnectorType, raw: dict[str, Any]) -> dict[str, Any]:
    if connector is ConnectorType.PAPER:
        return normalize_paper_settings(raw)
    if connector is ConnectorType.DERIV:
        return normalize_deriv_settings(raw)
    raise ConfigurationError(f"Unsupported connector {connector}")


def deriv_from(settings: dict[str, Any], secrets: dict[str, Any], app_id: str) -> DerivAdapter:
    token = str(secrets.get("token", "")).strip()
    if not token:
        raise ConfigurationError("Deriv token is missing")
    kind = str(secrets.get("token_kind", "pat"))
    if kind not in ("pat", "oauth"):
        raise ConfigurationError("Unknown Deriv token kind")
    try:
        return DerivAdapter(
            token=token,
            token_kind=kind,
            app_id=app_id,
            account_id=settings["account_id"],
            multiplier=settings.get("multiplier"),
        )
    except (ValueError, BrokerAuthErrorType) as exc:
        raise ConfigurationError(str(exc)) from exc


def build_temporary_adapter(
    db: Session,
    connector: ConnectorType,
    settings: dict[str, Any],
    secrets: dict[str, Any],
    *,
    deriv_app_id: str = "",
) -> BrokerAdapter:
    """An adapter for a connection that is not saved yet (Test Connection)."""
    if connector is ConnectorType.PAPER:
        market = build_market(db, settings)
        return PaperBroker(
            market,
            PaperConfig(
                account_id="PAPER-NEW",
                initial_balance=Decimal(settings["initial_balance"]),
                leverage=settings["leverage"],
            ),
        )
    if connector is ConnectorType.DERIV:
        return deriv_from(settings, secrets, deriv_app_id)
    raise ConfigurationError(f"Unsupported connector {connector}")


def decrypt_secrets(secret_box: SecretBox | None, ciphertext: str | None) -> dict[str, str]:
    if not ciphertext:
        return {}
    if secret_box is None:
        raise ConfigurationError("BROKER_CREDENTIALS_KEY is not configured on the engine")
    try:
        return secret_box.decrypt_json(ciphertext)
    except SecretBoxError as exc:
        raise ConfigurationError(
            "Stored credentials could not be decrypted (is BROKER_CREDENTIALS_KEY the same "
            "in backend/.env and trading-engine/.env?)"
        ) from exc


def build_market(db: Session, settings: dict[str, Any], now: datetime | None = None) -> SimMarket:
    now = now or paper_clock()
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
            raise ConfigurationError(
                f"Replay supports FX majors and R_10…R_100 only; {symbol} unknown"
            )
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
    deriv_app_id: str = "",
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
            rise_fall_payout_ratio=Decimal(settings["rise_fall_payout_ratio"]),
            multiplier_commission_pct=Decimal(settings["multiplier_commission_pct"]),
        )
        return PaperBroker(
            market,
            config,
            state=state_row.state if state_row else None,
            on_change=on_paper_change,
            faults=faults,
        )
    secrets = decrypt_secrets(secret_box, connection.credentials_encrypted)
    if connection.connector_type is ConnectorType.DERIV:
        settings = normalize_deriv_settings(connection.settings)
        return deriv_from(settings, secrets, deriv_app_id)
    raise ConfigurationError(f"Unsupported connector {connection.connector_type}")


def _uuid(value: Any) -> Any:
    import uuid

    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
