"""Broker connections from the engine's side: test, verify, sync.

Laravel owns the Add Broker wizard, stores connections and encrypts secrets.
The engine is asked to *prove* a connection works:

* `test_connection` connects with the submitted (encrypted) credentials and
  returns what the BROKER reports — account, environment, currency, balance,
  instruments, capabilities.
* `verify_environment` refuses a "DEMO" connection that is really LIVE, and
  refuses accounts whose type the broker does not confirm.
* `sync_account` / `sync_symbols` keep stored balances and instruments fresh.

Nothing is ever reported as connected without a successful broker call.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.deriv import DerivAdapter
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.factory import (
    ConfigurationError,
    build_temporary_adapter,
    decrypt_secrets,
    deriv_from,
    normalize_settings,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import AccountInfo, BrokerCapabilities
from fxrobot.core.crypto import SecretBox
from fxrobot.core.errors import UnprocessableError
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectorType
from fxrobot.models import AccountSnapshot, BrokerConnection, BrokerSymbol, TradingAccount
from fxrobot.notifications.service import notify


class ConnectionTestError(UnprocessableError):
    code = "connection_test_failed"


@dataclass
class ConnectionInput:
    connector_type: ConnectorType
    expected_environment: AccountEnvironment
    settings: dict[str, Any]
    credentials_encrypted: str | None = None


@dataclass
class TestOutcome:
    account: AccountInfo
    symbol_count: int
    categories: dict[str, int]
    capabilities: BrokerCapabilities
    normalized_settings: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def verify_environment(expected: AccountEnvironment, actual: AccountEnvironment) -> None:
    if actual is AccountEnvironment.UNKNOWN:
        raise ConnectionTestError(
            "The broker did not confirm whether this is a demo or a live account. "
            "For safety, 2kPilot refuses accounts of unknown type.",
            code="environment_unknown",
        )
    if expected is not actual:
        raise ConnectionTestError(
            f"You selected {expected.value}, but the broker reports a {actual.value} account. "
            "Nothing was saved.",
            code="environment_mismatch",
        )


def _normalize(data: ConnectionInput) -> dict[str, Any]:
    try:
        if data.connector_type is ConnectorType.PAPER:
            if data.expected_environment is not AccountEnvironment.PAPER:
                raise ConfigurationError("Paper connections are always PAPER")
        elif data.expected_environment not in (AccountEnvironment.DEMO, AccountEnvironment.LIVE):
            raise ConfigurationError("Choose DEMO or LIVE for a broker account")
        return normalize_settings(data.connector_type, data.settings)
    except ConfigurationError as exc:
        raise ConnectionTestError(str(exc), code="invalid_settings") from exc


def test_connection(
    db: Session, data: ConnectionInput, *, box: SecretBox | None, deriv_app_id: str
) -> TestOutcome:
    settings = _normalize(data)
    try:
        secrets = decrypt_secrets(box, data.credentials_encrypted)
        adapter = build_temporary_adapter(
            db, data.connector_type, settings, secrets, deriv_app_id=deriv_app_id
        )
    except ConfigurationError as exc:
        raise ConnectionTestError(str(exc), code="invalid_settings") from exc
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
    categories: dict[str, int] = {}
    for symbol in symbols:
        categories[symbol.category] = categories.get(symbol.category, 0) + 1
    return TestOutcome(
        account=account,
        symbol_count=len(symbols),
        categories=categories,
        capabilities=adapter.capabilities,
        normalized_settings=settings,
        warnings=warnings,
    )


def deriv_accounts(
    credentials_encrypted: str, *, box: SecretBox | None, deriv_app_id: str
) -> list[dict[str, str]]:
    """Options accounts reachable with a Deriv token (wizard step "choose account")."""
    try:
        secrets = decrypt_secrets(box, credentials_encrypted)
        adapter: DerivAdapter = deriv_from({"account_id": "LOOKUP"}, secrets, deriv_app_id)
    except ConfigurationError as exc:
        raise ConnectionTestError(str(exc), code="invalid_settings") from exc
    try:
        return [a.as_json() for a in adapter.list_accounts()]
    except BrokerError as exc:
        raise ConnectionTestError(f"Deriv refused the request: {exc}") from exc


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
    account.capabilities = adapter.capabilities.as_json()
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
        row.canonical = info.canonical_name[:20]
        row.description = info.description[:200]
        row.category = info.category
        row.base_currency, row.quote_currency = info.base_currency[:8], info.quote_currency[:8]
        row.digits, row.point, row.contract_size = info.digits, info.point, info.contract_size
        row.volume_min, row.volume_max = info.volume_min, info.volume_max
        row.volume_step, row.trade_allowed = info.volume_step, info.trade_allowed
        row.market_open = info.market_open
        db.add(row)
    db.commit()
    return len(symbols)
