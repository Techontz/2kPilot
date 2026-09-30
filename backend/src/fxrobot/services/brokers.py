"""Broker connections and trading accounts (the Add Broker wizard's backend).

Flow: choose type → choose DEMO/LIVE/PAPER → credentials → test → verify the
BROKER-REPORTED environment matches → pick a risk profile → save.

Safety rules:
* The broker's own report decides the environment. A "DEMO" connection that
  turns out to be LIVE (or UNKNOWN) is refused.
* Saving a LIVE account requires explicit acknowledgement, and the account
  can never trade while the server's LIVE hard lock is on.
* New accounts are saved with trading DISABLED.
* Secrets are encrypted before storage and are never returned.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.paper import PaperBroker, PaperConfig
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.factory import (
    ConfigurationError,
    build_market,
    mt5_from,
    normalize_mt5_settings,
    normalize_paper_settings,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.broker_engine.models import AccountInfo
from fxrobot.core.config import Settings
from fxrobot.core.crypto import SecretBox
from fxrobot.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectionStatus, ConnectorType, TradeStatus
from fxrobot.models import (
    AccountSnapshot,
    AuditOutcome,
    BrokerConnection,
    BrokerSymbol,
    RiskProfile,
    Trade,
    TradingAccount,
    User,
)
from fxrobot.notifications.service import notify
from fxrobot.services import audit
from fxrobot.services.context import RequestMeta


class ConnectionTestError(AppError):
    code = "connection_test_failed"


@dataclass
class ConnectionInput:
    connector_type: ConnectorType
    expected_environment: AccountEnvironment
    settings: dict[str, Any]
    credentials: dict[str, str] = field(default_factory=dict)
    label: str = ""


@dataclass
class TestOutcome:
    account: AccountInfo
    symbol_count: int
    warnings: list[str]
    normalized_settings: dict[str, Any]


def secret_box(settings: Settings) -> SecretBox | None:
    key = settings.secret_encryption_key.get_secret_value()
    return SecretBox(key) if key else None


# ── validation & testing ─────────────────────────────────────────────────


def _normalize(data: ConnectionInput) -> dict[str, Any]:
    try:
        if data.connector_type is ConnectorType.PAPER:
            if data.expected_environment is not AccountEnvironment.PAPER:
                raise ConfigurationError("Paper connections are always PAPER")
            return normalize_paper_settings(data.settings)
        if data.expected_environment not in (AccountEnvironment.DEMO, AccountEnvironment.LIVE):
            raise ConfigurationError("Choose DEMO or LIVE for a MetaTrader 5 account")
        merged = {
            **data.settings,
            "login": data.settings.get("login") or data.credentials.get("login", ""),
        }
        merged["server"] = data.settings.get("server") or data.credentials.get("server", "")
        return normalize_mt5_settings(merged)
    except ConfigurationError as exc:
        raise ConnectionTestError(str(exc), code="invalid_settings") from exc


def _temporary_adapter(
    db: Session, data: ConnectionInput, settings: dict[str, Any]
) -> BrokerAdapter:
    try:
        if data.connector_type is ConnectorType.PAPER:
            market = build_market(db, settings)
            return PaperBroker(
                market,
                PaperConfig(
                    account_id="PAPER-NEW",
                    initial_balance=Decimal(settings["initial_balance"]),
                    leverage=settings["leverage"],
                ),
            )
        secret = data.credentials.get("bridge_secret", "")
        password = data.credentials.get("password", "")
        if not password:
            raise ConfigurationError("MT5 password is required")
        return mt5_from(settings, {"bridge_secret": secret, "password": password})
    except ConfigurationError as exc:
        raise ConnectionTestError(str(exc), code="invalid_settings") from exc


def verify_environment(expected: AccountEnvironment, actual: AccountEnvironment) -> None:
    if actual is AccountEnvironment.UNKNOWN:
        raise ConnectionTestError(
            "The broker did not confirm whether this is a demo or a live account. "
            "For safety, 2kFX refuses accounts of unknown type.",
            code="environment_unknown",
        )
    if expected is not actual:
        raise ConnectionTestError(
            f"You selected {expected.value}, but the broker reports a {actual.value} account. "
            "Nothing was saved.",
            code="environment_mismatch",
        )


def test_connection(db: Session, data: ConnectionInput) -> TestOutcome:
    settings = _normalize(data)
    adapter = _temporary_adapter(db, data, settings)
    warnings: list[str] = []
    try:
        account = adapter.test_connection()
        symbols = adapter.get_symbols()
    except BrokerError as exc:
        raise ConnectionTestError(f"Connection test failed: {exc}") from exc
    finally:
        with contextlib.suppress(BrokerError):
            adapter.disconnect()
    verify_environment(data.expected_environment, account.environment)
    if not account.trade_allowed:
        warnings.append("The broker reports trading is not allowed on this account.")
    if data.connector_type is ConnectorType.MT5_BRIDGE and settings["bridge_url"].startswith(
        "http://"
    ):
        warnings.append("The bridge uses plain HTTP. Use HTTPS or a private tunnel (see docs).")
    return TestOutcome(account, len(symbols), warnings, settings)


# ── persistence ──────────────────────────────────────────────────────────


def create_connection(
    db: Session,
    data: ConnectionInput,
    *,
    actor: User,
    meta: RequestMeta,
    settings: Settings,
    risk_profile_id: uuid.UUID | None,
    acknowledge_live: bool,
) -> TradingAccount:
    if data.expected_environment is AccountEnvironment.LIVE and not acknowledge_live:
        raise PermissionDeniedError(
            "Adding a LIVE (real-money) account requires explicit acknowledgement.",
            code="live_ack_required",
        )
    if risk_profile_id is not None and db.get(RiskProfile, risk_profile_id) is None:
        raise NotFoundError("Risk profile not found")
    outcome = test_connection(db, data)
    credentials_encrypted = None
    if data.connector_type is ConnectorType.MT5_BRIDGE:
        box = secret_box(settings)
        if box is None:
            raise ConnectionTestError(
                "SECRET_ENCRYPTION_KEY is not configured on the server, so credentials "
                "cannot be stored safely.",
                code="encryption_unavailable",
            )
        credentials_encrypted = box.encrypt(
            json.dumps(
                {
                    "password": data.credentials.get("password", ""),
                    "bridge_secret": data.credentials.get("bridge_secret", ""),
                }
            )
        )
    existing = db.scalar(
        select(TradingAccount)
        .join(BrokerConnection)
        .where(
            TradingAccount.broker_account_id == outcome.account.account_id,
            BrokerConnection.connector_type == data.connector_type,
            TradingAccount.server == outcome.account.server,
        )
    )
    if existing is not None and data.connector_type is not ConnectorType.PAPER:
        raise ConflictError("This broker account is already connected")

    account_info = outcome.account
    label = data.label.strip() or (
        "Paper account"
        if data.connector_type is ConnectorType.PAPER
        else f"MT5 {account_info.account_id}"
    )
    connection = BrokerConnection(
        label=label[:120],
        connector_type=data.connector_type,
        expected_environment=data.expected_environment,
        settings=outcome.normalized_settings,
        credentials_encrypted=credentials_encrypted,
        status=ConnectionStatus.DISCONNECTED,
        status_detail="Verified — not connected yet",
        created_by=actor.id,
    )
    db.add(connection)
    db.flush()
    broker_account_id = account_info.account_id
    if data.connector_type is ConnectorType.PAPER:
        broker_account_id = f"PAPER-{str(connection.id)[:8].upper()}"
    account = TradingAccount(
        connection_id=connection.id,
        broker_account_id=broker_account_id,
        label=label[:120],
        name=account_info.name,
        server=account_info.server,
        currency=account_info.currency,
        environment=account_info.environment,
        leverage=account_info.leverage,
        trading_enabled=False,
        risk_profile_id=risk_profile_id,
        balance=account_info.balance,
        equity=account_info.equity,
        margin=account_info.margin,
        free_margin=account_info.free_margin,
        margin_level=account_info.margin_level,
        synced_at=utcnow(),
    )
    db.add(account)
    db.flush()
    audit.record(
        db,
        action="broker.added",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="broker_connection",
        target_id=str(connection.id),
        details={
            "type": data.connector_type.value,
            "environment": account.environment.value,
            "account": broker_account_id,
            "server": account.server,
        },
    )
    db.commit()
    notify(
        db,
        "broker.connected",
        f"{label} ({account.environment.value}) verified and saved. Trading is disabled "
        "until you enable it.",
        account_id=account.id,
    )
    return account


def delete_connection(
    db: Session,
    connection_id: uuid.UUID,
    *,
    actor: User,
    meta: RequestMeta,
    manager: BrokerManager,
) -> None:
    connection = db.get(BrokerConnection, connection_id)
    if connection is None:
        raise NotFoundError("Connection not found")
    account_ids = [a.id for a in connection.accounts]
    open_trades = (
        db.scalar(
            select(Trade.id).where(
                Trade.account_id.in_(account_ids), Trade.status == TradeStatus.OPEN
            )
        )
        if account_ids
        else None
    )
    if open_trades is not None:
        raise ConflictError("Close all open positions on this account before removing it")
    manager.evict(connection_id)
    audit.record(
        db,
        action="broker.removed",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="broker_connection",
        target_id=str(connection_id),
        details={"label": connection.label},
    )
    db.delete(connection)
    db.commit()


def update_account(
    db: Session,
    account_id: uuid.UUID,
    *,
    actor: User,
    meta: RequestMeta,
    settings: Settings,
    label: str | None = None,
    trading_enabled: bool | None = None,
    risk_profile_id: uuid.UUID | None = None,
    clear_risk_profile: bool = False,
) -> TradingAccount:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    changes: dict[str, Any] = {}
    if label is not None:
        account.label = label.strip()[:120] or account.label
        changes["label"] = account.label
    if clear_risk_profile:
        account.risk_profile_id = None
        changes["risk_profile_id"] = None
    elif risk_profile_id is not None:
        if db.get(RiskProfile, risk_profile_id) is None:
            raise NotFoundError("Risk profile not found")
        account.risk_profile_id = risk_profile_id
        changes["risk_profile_id"] = str(risk_profile_id)
    if trading_enabled is not None and trading_enabled != account.trading_enabled:
        if trading_enabled:
            problem = _enable_problem(account, settings)
            if problem:
                audit.record(
                    db,
                    action="account.trading_enable_denied",
                    outcome=AuditOutcome.DENIED,
                    actor=actor,
                    meta=meta,
                    target_type="trading_account",
                    target_id=str(account.id),
                    details={"reason": problem},
                )
                db.commit()
                raise PermissionDeniedError(problem)
        account.trading_enabled = trading_enabled
        changes["trading_enabled"] = trading_enabled
    if not account.risk_profile_id and account.trading_enabled:
        account.trading_enabled = False  # never trade without a risk profile
        changes["trading_enabled"] = False
    if changes:
        audit.record(
            db,
            action="account.updated",
            outcome=AuditOutcome.SUCCESS,
            actor=actor,
            meta=meta,
            target_type="trading_account",
            target_id=str(account.id),
            details=changes,
        )
    db.commit()
    return account


def _enable_problem(account: TradingAccount, settings: Settings) -> str | None:
    if account.risk_profile_id is None:
        return "Assign a risk profile before enabling trading."
    if account.environment is AccountEnvironment.UNKNOWN:
        return "Accounts of unknown type (demo/live) can never trade."
    if account.environment is AccountEnvironment.LIVE and not settings.live_trading_enabled:
        return "LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false)."
    return None


# ── synchronisation ──────────────────────────────────────────────────────


def sync_account(
    db: Session, account: TradingAccount, adapter: BrokerAdapter, *, snapshot: bool = True
) -> AccountInfo:
    info = adapter.get_account()
    if info.environment is not account.environment and not (
        account.environment is AccountEnvironment.PAPER and adapter.is_simulated
    ):
        # The broker now reports a different environment: stop trading immediately.
        account.trading_enabled = False
        notify(
            db,
            "broker.error",
            f"{account.label}: broker now reports {info.environment.value} but the account was "
            f"saved as {account.environment.value}. Trading disabled.",
            account_id=account.id,
            commit=False,
        )
    account.balance, account.equity = info.balance, info.equity
    account.margin, account.free_margin = info.margin, info.free_margin
    account.margin_level, account.leverage = info.margin_level, info.leverage
    account.synced_at = utcnow()
    if snapshot:
        db.add(
            AccountSnapshot(
                account_id=account.id,
                taken_at=adapter.now(),
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                open_positions=len(adapter.get_positions()),
            )
        )
    db.commit()
    return info


def sync_symbols(db: Session, connection: BrokerConnection, adapter: BrokerAdapter) -> int:
    symbols = adapter.get_symbols()
    existing = {
        s.name: s
        for s in db.scalars(select(BrokerSymbol).where(BrokerSymbol.connection_id == connection.id))
    }
    for info in symbols:
        row = existing.get(info.name) or BrokerSymbol(connection_id=connection.id, name=info.name)
        row.canonical = info.canonical_name
        row.description = info.description[:200]
        row.base_currency, row.quote_currency = info.base_currency, info.quote_currency
        row.digits, row.point, row.contract_size = info.digits, info.point, info.contract_size
        row.volume_min, row.volume_max = info.volume_min, info.volume_max
        row.volume_step, row.trade_allowed = info.volume_step, info.trade_allowed
        db.add(row)
    db.commit()
    return len(symbols)


def list_accounts(db: Session) -> list[TradingAccount]:
    return list(db.scalars(select(TradingAccount).order_by(TradingAccount.created_at)))


def list_connections(db: Session) -> list[BrokerConnection]:
    return list(db.scalars(select(BrokerConnection).order_by(BrokerConnection.created_at)))
