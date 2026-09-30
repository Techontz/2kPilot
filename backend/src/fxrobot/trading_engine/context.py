"""Build the risk engine's context from the database and the live broker."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import AccountInfo, Quote
from fxrobot.domain.market import SymbolInfo
from fxrobot.domain.trading import TradeStatus
from fxrobot.models import AccountSnapshot, SystemState, Trade, TradingAccount
from fxrobot.risk_engine.engine import OpenExposure, RiskContext


def day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(moment: datetime) -> datetime:
    return day_start(moment) - timedelta(days=moment.weekday())


def build_risk_context(
    db: Session,
    *,
    account: TradingAccount,
    adapter: BrokerAdapter,
    state: SystemState,
    live_locked: bool,
    symbol: SymbolInfo,
    account_info: AccountInfo | None,
    broker_connected: bool,
) -> RiskContext:
    now = adapter.now()
    quote_cache: dict[str, Quote | None] = {}

    def lookup(name: str) -> Quote | None:
        if name not in quote_cache:
            try:
                quote_cache[name] = adapter.get_quote(name)
            except BrokerError:
                quote_cache[name] = None
        return quote_cache[name]

    quote = lookup(symbol.name)
    open_trades = list(
        db.scalars(
            select(Trade).where(Trade.account_id == account.id, Trade.status == TradeStatus.OPEN)
        )
    )
    try:
        positions = adapter.get_positions()
    except BrokerError:
        positions = None
    risk_by_position = {t.broker_position_id: t.risk_amount for t in open_trades}
    if positions is None:  # unknown broker state: represent with DB trades, risk unknown
        exposures = [OpenExposure(t.symbol, t.side, t.volume, None) for t in open_trades]
        unrealized = Decimal(0)
    else:
        exposures = [
            OpenExposure(p.symbol, p.side, p.volume, risk_by_position.get(p.position_id))
            for p in positions
        ]
        unrealized = sum((p.unrealized_pnl for p in positions), Decimal(0))

    d0, w0 = day_start(now), week_start(now)

    def realized_since(start: datetime) -> Decimal:
        value = db.scalar(
            select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(
                Trade.account_id == account.id,
                Trade.status == TradeStatus.CLOSED,
                Trade.exit_time >= start,
            )
        )
        return Decimal(str(value or 0))

    realized_today, realized_week = realized_since(d0), realized_since(w0)
    trades_today = int(
        db.scalar(
            select(func.count()).where(Trade.account_id == account.id, Trade.entry_time >= d0)
        )
        or 0
    )
    recent = list(
        db.scalars(
            select(Trade)
            .where(
                Trade.account_id == account.id,
                Trade.status == TradeStatus.CLOSED,
                Trade.net_pnl.is_not(None),
            )
            .order_by(Trade.exit_time.desc())
            .limit(20)
        )
    )
    consecutive = 0
    for trade in recent:
        if trade.net_pnl is not None and trade.net_pnl < 0:
            consecutive += 1
        else:
            break
    last_loss = recent[0].exit_time if recent and consecutive else None

    balance = account_info.balance if account_info else account.balance
    equity = account_info.equity if account_info else account.equity
    peak = db.scalar(
        select(func.max(AccountSnapshot.equity)).where(AccountSnapshot.account_id == account.id)
    )
    peak_equity = max(filter(None, [peak, equity]), default=None)
    return RiskContext(
        now=now,
        mode=state.trading_mode,
        kill_switch_engaged=state.kill_switch_engaged,
        live_trading_locked=live_locked,
        account_environment=account.environment,
        account_trading_enabled=account.trading_enabled,
        broker_connected=broker_connected,
        account_currency=account.currency,
        balance=balance,
        equity=equity,
        free_margin=account_info.free_margin if account_info else account.free_margin,
        leverage=account_info.leverage if account_info else account.leverage,
        symbol=symbol,
        quote=quote,
        quote_lookup=lookup,
        open_positions=exposures,
        realized_pnl_today=realized_today,
        realized_pnl_week=realized_week,
        unrealized_pnl=unrealized,
        start_of_day_balance=(balance - realized_today) if balance is not None else None,
        start_of_week_balance=(balance - realized_week) if balance is not None else None,
        peak_equity=peak_equity,
        trades_today=trades_today,
        consecutive_losses=consecutive,
        last_loss_at=last_loss,
    )
