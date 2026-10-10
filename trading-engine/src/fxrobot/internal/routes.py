"""Internal endpoints. Thin: validate input, call a service, serialise.

Laravel authenticates the user and checks ownership BEFORE calling; requests
that act for a user carry that user's id (`user_id` / `actor_id`) or the
exact account ids to act on.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from fxrobot import __version__
from fxrobot.backtesting.service import BacktestRequest, BacktestService
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.config import Settings
from fxrobot.core.crypto import SecretBox
from fxrobot.core.errors import BrokerUnavailableError, NotFoundError, UnprocessableError
from fxrobot.domain.contracts import ContractFamily, ContractSpec
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectorType, OrderType
from fxrobot.internal import serializers as out
from fxrobot.market_data.sessions import is_fx_market_open, session_at
from fxrobot.models import BrokerConnection, SystemState, TradingAccount
from fxrobot.services import brokers, market_data, strategies, trading_ops
from fxrobot.services.strategy_drafts import StrategyDrafter

router = APIRouter(prefix="/internal")


# ── dependencies ─────────────────────────────────────────────────────────


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


Db = Annotated[Session, Depends(get_db)]


def settings_of(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def manager_of(request: Request) -> BrokerManager:
    return request.app.state.broker_manager  # type: ignore[no-any-return]


def box_of(request: Request) -> SecretBox | None:
    return request.app.state.secret_box  # type: ignore[no-any-return]


def _account(db: Session, account_id: uuid.UUID) -> TradingAccount:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    return account


def _adapter(request: Request, account: TradingAccount):  # type: ignore[no-untyped-def]
    try:
        return manager_of(request).get(account.connection_id)
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Broker unavailable: {exc}") from exc


# ── health ───────────────────────────────────────────────────────────────


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
def health(request: Request, db: Db) -> dict[str, Any]:
    settings = settings_of(request)
    db.execute(text("SELECT 1"))
    state = db.get(SystemState, 1)
    engine = request.app.state.trading_engine
    return {
        "status": "ok",
        "version": __version__,
        "database": "ok",
        "engine_enabled": settings.engine_enabled,
        "engine_leader": engine.is_leader,
        "engine_heartbeat_at": state.engine_heartbeat_at.isoformat()
        if state and state.engine_heartbeat_at
        else None,
        "live_trading_enabled": settings.live_trading_enabled,
        "broker_credentials_key": box_of(request) is not None,
        "deriv_app_id_configured": bool(settings.deriv_app_id),
    }


# ── strategies ───────────────────────────────────────────────────────────


@router.get("/strategies")
def strategy_catalog() -> list[dict[str, Any]]:
    return strategies.catalog()


class ParamsIn(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.post("/strategies/{key}/validate")
def validate_parameters(key: str, body: ParamsIn) -> dict[str, Any]:
    return strategies.validate_params(key, body.parameters)


def drafter_of(request: Request) -> StrategyDrafter:
    return request.app.state.drafter  # type: ignore[no-any-return]


@router.get("/strategies/catalog")
def rules_catalog(request: Request) -> dict[str, Any]:
    """Indicators, operators, fields and limits for the visual rule builder."""
    return strategies.rules_catalog(ai_drafting_available=drafter_of(request).available)


class DraftIn(BaseModel):
    description: str = Field(min_length=10, max_length=2000)
    symbol: str | None = Field(default=None, max_length=40)
    timeframe: Timeframe | None = None
    contract_family: ContractFamily | None = None


@router.post("/strategies/draft")
def draft_strategy(request: Request, body: DraftIn) -> dict[str, Any]:
    """Plain English → a DRAFT rule set (never saved here; the user reviews it)."""
    return drafter_of(request).draft(
        body.description,
        symbol=body.symbol,
        timeframe=body.timeframe,
        contract_family=body.contract_family.value if body.contract_family else None,
    )


# ── connections ──────────────────────────────────────────────────────────


class ConnectionTestIn(BaseModel):
    connector_type: ConnectorType
    expected_environment: AccountEnvironment
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials_encrypted: str | None = Field(default=None, max_length=20_000)


@router.post("/connections/test")
def test_connection(request: Request, db: Db, body: ConnectionTestIn) -> dict[str, Any]:
    outcome = brokers.test_connection(
        db,
        brokers.ConnectionInput(
            body.connector_type,
            body.expected_environment,
            body.settings,
            body.credentials_encrypted,
        ),
        box=box_of(request),
        deriv_app_id=settings_of(request).deriv_app_id,
    )
    return {
        "account": out.account(outcome.account),
        "symbol_count": outcome.symbol_count,
        "categories": outcome.categories,
        "capabilities": outcome.capabilities.as_json(),
        "normalized_settings": outcome.normalized_settings,
        "warnings": outcome.warnings,
    }


class DerivAccountsIn(BaseModel):
    credentials_encrypted: str = Field(max_length=20_000)


@router.post("/deriv/accounts")
def deriv_accounts(request: Request, body: DerivAccountsIn) -> list[dict[str, str]]:
    return brokers.deriv_accounts(
        body.credentials_encrypted,
        box=box_of(request),
        deriv_app_id=settings_of(request).deriv_app_id,
    )


@router.post("/connections/{connection_id}/connect")
def connect(request: Request, db: Db, connection_id: uuid.UUID) -> dict[str, Any]:
    """Connect now (after saving, or "Reconnect"), then sync account and instruments."""
    connection = db.get(BrokerConnection, connection_id)
    if connection is None:
        raise NotFoundError("Connection not found")
    manager = manager_of(request)
    manager.evict(connection_id)  # pick up new settings/credentials
    try:
        adapter = manager.get(connection_id)
        symbols = brokers.sync_symbols(db, connection, adapter)
        for account in connection.accounts:
            brokers.sync_account(db, account, adapter)
    except BrokerError as exc:
        db.rollback()
        raise BrokerUnavailableError(f"Could not connect: {exc}") from exc
    db.refresh(connection)
    return {
        "status": connection.status.value,
        "detail": connection.status_detail,
        "symbols": symbols,
    }


@router.post("/connections/{connection_id}/disconnect")
def disconnect(request: Request, connection_id: uuid.UUID) -> dict[str, str]:
    manager_of(request).disconnect(connection_id)
    return {"status": "DISCONNECTED"}


# ── accounts & market data ───────────────────────────────────────────────


@router.post("/accounts/{account_id}/sync")
def sync(request: Request, db: Db, account_id: uuid.UUID) -> dict[str, Any]:
    account = _account(db, account_id)
    adapter = _adapter(request, account)
    try:
        info = brokers.sync_account(db, account, adapter, snapshot=False)
    except BrokerError as exc:
        db.rollback()
        raise BrokerUnavailableError(f"Sync failed: {exc}") from exc
    return out.account(info)


@router.get("/accounts/{account_id}/symbols")
def symbols(request: Request, db: Db, account_id: uuid.UUID) -> list[dict[str, Any]]:
    account = _account(db, account_id)
    adapter = _adapter(request, account)
    connection = db.get(BrokerConnection, account.connection_id)
    try:
        if connection is not None:
            brokers.sync_symbols(db, connection, adapter)
        return [out.symbol(s) for s in adapter.get_symbols()]
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Instruments unavailable: {exc}") from exc


@router.get("/accounts/{account_id}/symbols/{symbol}")
def symbol_detail(request: Request, db: Db, account_id: uuid.UUID, symbol: str) -> dict[str, Any]:
    adapter = _adapter(request, _account(db, account_id))
    try:
        return out.symbol(adapter.get_symbol(symbol))
    except BrokerError as exc:
        raise NotFoundError(str(exc)) from exc


@router.get("/accounts/{account_id}/quotes")
def quotes(
    request: Request,
    db: Db,
    account_id: uuid.UUID,
    symbols: Annotated[str, Query(max_length=2000)],
) -> dict[str, Any]:
    adapter = _adapter(request, _account(db, account_id))
    result: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in [s.strip() for s in symbols.split(",") if s.strip()][:60]:
        try:
            result[name] = out.quote(adapter.get_quote(name))
        except BrokerError as exc:
            errors[name] = str(exc)
    return {"quotes": result, "errors": errors, "simulated": adapter.is_simulated}


@router.get("/accounts/{account_id}/candles")
def candles(
    request: Request,
    db: Db,
    account_id: uuid.UUID,
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    count: Annotated[int, Query(ge=10, le=1000)] = 200,
) -> dict[str, Any]:
    adapter = _adapter(request, _account(db, account_id))
    end = adapter.now()
    start = end - timeframe.delta * count * 2 - timedelta(days=3)
    try:
        rows = adapter.get_candles(symbol, timeframe, start, end)[-count:]
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Candles unavailable: {exc}") from exc
    return {"candles": [out.candle(c) for c in rows], "simulated": adapter.is_simulated}


class UnsupportedContractError(UnprocessableError):
    code = "unsupported_contract"


def _spec(raw: dict[str, Any] | None) -> ContractSpec:
    try:
        return ContractSpec.parse(raw)
    except ValueError as exc:
        raise UnsupportedContractError(f"Invalid contract settings: {exc}") from exc


@router.get("/accounts/{account_id}/contracts")
def contracts(
    request: Request,
    db: Db,
    account_id: uuid.UUID,
    symbol: Annotated[str, Query(min_length=1, max_length=40)],
) -> dict[str, Any]:
    """Which contracts the account's broker offers on `symbol` (Deriv: contracts_for)."""
    adapter = _adapter(request, _account(db, account_id))
    try:
        caps = adapter.contract_capabilities(symbol)
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Contract offer unavailable: {exc}") from exc
    data: dict[str, Any] = caps.as_json()
    if not caps.spot and not caps.rise_fall and not caps.multipliers:
        data["notes"] = [*data["notes"], f"No supported contracts on {symbol}."]
    data["fetched_at"] = datetime.now(UTC).isoformat()
    return data


class ContractCheckIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    contract: dict[str, Any] = Field(default_factory=dict)


@router.post("/accounts/{account_id}/contracts/validate")
def validate_contract(
    request: Request, db: Db, account_id: uuid.UUID, body: ContractCheckIn
) -> dict[str, Any]:
    """Is this contract spec tradeable on this account and symbol? 422 with a reason if not."""
    spec = _spec(body.contract)
    adapter = _adapter(request, _account(db, account_id))
    if spec.contract_family.value not in adapter.capabilities.contract_families:
        raise UnsupportedContractError(
            f"{spec.label()} is not offered by {adapter.connector_id.capitalize()}."
        )
    if spec.contract_family.is_contract:
        try:
            problem = adapter.contract_capabilities(body.symbol).check(spec)
        except BrokerError as exc:
            raise BrokerUnavailableError(f"Contract offer unavailable: {exc}") from exc
        if problem:
            raise UnsupportedContractError(problem)
    return {"ok": True, "contract": spec.as_json()}


@router.get("/market/session")
def market_session() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "now": now.isoformat(),
        "session": session_at(now).value,
        "fx_open": is_fx_market_open(now),
    }


# ── manual tickets ───────────────────────────────────────────────────────


class TicketIn(BaseModel):
    account_id: uuid.UUID
    symbol: str = Field(min_length=1, max_length=40)
    side: Side
    order_type: OrderType = OrderType.MARKET
    volume: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=4)
    stop_loss: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=10)
    take_profit: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=10)
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=64)
    actor_id: uuid.UUID | None = None
    actor_label: str = Field(default="dashboard", max_length=320)
    contract: dict[str, Any] | None = None  # canonical contract spec; None = SPOT

    def ticket(self) -> trading_ops.ManualTicket:
        return trading_ops.ManualTicket(
            account_id=self.account_id,
            symbol=self.symbol,
            side=self.side,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            volume=self.volume,
            order_type=self.order_type,
            idempotency_key=self.idempotency_key,
            actor_id=self.actor_id,
            actor_label=self.actor_label,
            contract=_spec(self.contract),
        )


@router.post("/orders/preview")
def preview(request: Request, db: Db, body: TicketIn) -> dict[str, Any]:
    result = trading_ops.preview_ticket(
        db,
        manager_of(request),
        body.ticket(),
        live_locked=not settings_of(request).live_trading_enabled,
    )
    data = out.plain(result)
    data["symbol"] = out.symbol(result.symbol) if result.symbol else None
    return data  # type: ignore[no-any-return]


@router.post("/orders")
def submit(request: Request, db: Db, body: TicketIn) -> dict[str, Any]:
    signal = trading_ops.submit_ticket(
        db,
        manager_of(request),
        body.ticket(),
        live_locked=not settings_of(request).live_trading_enabled,
    )
    return trading_ops.ticket_result(db, signal)


# ── positions ────────────────────────────────────────────────────────────


class ActorIn(BaseModel):
    actor_label: str = Field(default="dashboard", max_length=320)


class ModifyIn(ActorIn):
    stop_loss: Decimal = Field(gt=0, max_digits=24, decimal_places=10)
    take_profit: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=10)


class CloseAllIn(ActorIn):
    # The user's own accounts (Laravel resolves them). Nothing else is closed.
    account_ids: list[uuid.UUID] = Field(max_length=1000)


@router.post("/positions/close-all")
def close_all(request: Request, db: Db, body: CloseAllIn) -> dict[str, Any]:
    return trading_ops.close_all_positions(
        db, manager_of(request), account_ids=body.account_ids, actor_label=body.actor_label
    )


@router.post("/positions/{trade_id}/close")
def close(request: Request, db: Db, trade_id: uuid.UUID, body: ActorIn) -> dict[str, Any]:
    order = trading_ops.close_position(
        db, manager_of(request), trade_id, actor_label=body.actor_label
    )
    return {"order_status": order.status.value, "fill_price": out.plain(order.fill_price)}


@router.put("/positions/{trade_id}")
def modify(request: Request, db: Db, trade_id: uuid.UUID, body: ModifyIn) -> dict[str, Any]:
    trade = trading_ops.modify_position(
        db,
        manager_of(request),
        trade_id,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        actor_label=body.actor_label,
    )
    return {"stop_loss": out.plain(trade.stop_loss), "take_profit": out.plain(trade.take_profit)}


# ── backtests ────────────────────────────────────────────────────────────


class BacktestIn(BaseModel):
    mode: Literal["single", "split", "walk_forward", "sensitivity"] = "single"
    strategy_key: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    strategy_version_id: uuid.UUID | None = None
    dataset_id: uuid.UUID
    start: datetime
    end: datetime
    initial_capital: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    risk: dict[str, Any] = Field(default_factory=dict)
    costs: dict[str, Any] = Field(default_factory=dict)
    name: str = Field(default="", max_length=200)
    split_ratio: float = 0.7
    train_months: int = Field(default=6, ge=1, le=36)
    test_months: int = Field(default=2, ge=1, le=12)
    grid: dict[str, list[Any]] = Field(default_factory=dict)
    actor_id: uuid.UUID  # the user who owns the backtest
    contract: dict[str, Any] | None = None  # canonical contract spec; None = SPOT
    # Rise/Fall profit per 1 of stake when won — an ESTIMATE (live payouts vary).
    payout_ratio: Decimal = Field(default=Decimal("0.95"), ge=Decimal("0.01"), le=Decimal(2))
    commission_pct: Decimal = Field(default=Decimal(0), ge=0, le=Decimal(10))  # Multipliers


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.post("/backtests")
def create_backtest(request: Request, db: Db, body: BacktestIn) -> dict[str, Any]:
    service: BacktestService = request.app.state.backtests
    row = service.create(
        db,
        BacktestRequest(
            mode=body.mode,
            strategy_key=body.strategy_key,
            parameters=body.parameters,
            dataset_id=body.dataset_id,
            start=_aware(body.start),
            end=_aware(body.end),
            initial_capital=body.initial_capital,
            risk=body.risk,
            costs=body.costs,
            strategy_version_id=body.strategy_version_id,
            name=body.name,
            split_ratio=body.split_ratio,
            train_months=body.train_months,
            test_months=body.test_months,
            grid=body.grid,
            contract=body.contract or {},
            payout_ratio=body.payout_ratio,
            commission_pct=body.commission_pct,
        ),
        body.actor_id,
        run_async=False,  # Laravel's queue job runs it via /run
    )
    return {"id": str(row.id), "status": row.status.value}


@router.post("/backtests/{backtest_id}/run")
def run_backtest(request: Request, backtest_id: uuid.UUID) -> dict[str, Any]:
    service: BacktestService = request.app.state.backtests
    service.execute(backtest_id)
    with request.app.state.session_factory() as db:
        from fxrobot.models import Backtest

        row = db.get(Backtest, backtest_id)
        if row is None:
            raise NotFoundError("Backtest not found")
        return {"id": str(row.id), "status": row.status.value, "error": row.error}


# ── datasets ─────────────────────────────────────────────────────────────


class SyntheticIn(BaseModel):
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    days: int = Field(default=365, ge=30, le=3650)
    seed: int = Field(default=42, ge=0, le=2**31)
    user_id: uuid.UUID | None = None  # owner; None = a shared dataset


@router.post("/datasets/synthetic")
def synthetic(db: Db, body: SyntheticIn) -> dict[str, Any]:
    dataset = market_data.generate_synthetic(
        db,
        symbol=body.symbol,
        timeframe=body.timeframe,
        days=body.days,
        seed=body.seed,
        user_id=body.user_id,
    )
    return {"id": str(dataset.id), "bars": dataset.bar_count}


class CsvIn(BaseModel):
    symbol: str
    timeframe: Timeframe
    content: str = Field(max_length=60_000_000)
    utc_offset_hours: float = Field(default=0, ge=-14, le=14)
    filename: str = Field(default="upload.csv", max_length=200)
    user_id: uuid.UUID | None = None


@router.post("/datasets/import")
def import_csv(db: Db, body: CsvIn) -> dict[str, Any]:
    dataset, report = market_data.import_csv(
        db,
        symbol=body.symbol,
        timeframe=body.timeframe,
        content=body.content,
        utc_offset_hours=body.utc_offset_hours,
        filename=body.filename,
        user_id=body.user_id,
    )
    return {"id": str(dataset.id), "report": out.plain(report)}


class DownloadIn(BaseModel):
    account_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    start: datetime
    end: datetime
    user_id: uuid.UUID | None = None


@router.post("/datasets/download")
def download(request: Request, db: Db, body: DownloadIn) -> dict[str, Any]:
    account = _account(db, body.account_id)
    adapter = _adapter(request, account)
    dataset = market_data.download_from_broker(
        db,
        adapter,
        connection_id=account.connection_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        start=_aware(body.start),
        end=_aware(body.end),
        user_id=body.user_id,
    )
    return {"id": str(dataset.id), "bars": dataset.bar_count}
