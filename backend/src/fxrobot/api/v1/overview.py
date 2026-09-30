"""One call that answers the Overview's questions (keeps the dashboard light)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep
from fxrobot.domain.trading import AssignmentStatus, TradeStatus
from fxrobot.models import AccountSnapshot, StrategyAssignment, Trade, TradeEvent, TradingAccount
from fxrobot.trading_engine.context import day_start

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("")
def overview(_: CurrentUserDep, db: DbDep, manager: ManagerDep) -> dict[str, Any]:
    accounts = list(db.scalars(select(TradingAccount).order_by(TradingAccount.created_at)))
    ids = [a.id for a in accounts]
    today = day_start(datetime.now(UTC))
    open_trades = (
        list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))) if ids else []
    )
    closed_today = (
        db.scalar(
            select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(
                Trade.status == TradeStatus.CLOSED, Trade.exit_time >= today
            )
        )
        if ids
        else 0
    )
    trades_today = db.scalar(select(func.count()).where(Trade.entry_time >= today)) if ids else 0
    open_pnl = sum((t.unrealized_pnl or Decimal(0) for t in open_trades), Decimal(0))
    open_risk = sum((t.risk_amount or Decimal(0) for t in open_trades), Decimal(0))
    unknown_risk = any(t.risk_amount is None for t in open_trades)
    currency = accounts[0].currency if accounts else "USD"
    per_account = []
    for a in accounts:
        peak = db.scalar(
            select(func.max(AccountSnapshot.equity)).where(AccountSnapshot.account_id == a.id)
        )
        dd = None
        if peak and a.equity is not None and peak > 0:
            dd = float(max(Decimal(0), (peak - a.equity) / peak * 100).quantize(Decimal("0.01")))
        live = (
            manager.status(a.connection_id).value
            if manager.peek(a.connection_id)
            else a.connection.status.value
        )
        per_account.append(
            ser.account(
                a,
                connection_status=live,
                drawdown_pct=dd,
                connector_type=a.connection.connector_type.value,
            )
        )
    equity_series = []
    if len(accounts) >= 1:
        first = accounts[0]
        snaps = list(
            db.scalars(
                select(AccountSnapshot)
                .where(AccountSnapshot.account_id == first.id)
                .order_by(AccountSnapshot.taken_at.desc())
                .limit(500)
            )
        )
        equity_series = [
            {"t": s.taken_at.isoformat(), "equity": float(s.equity), "balance": float(s.balance)}
            for s in reversed(snaps)
        ]
    active = (
        db.scalar(select(func.count()).where(StrategyAssignment.status == AssignmentStatus.ENABLED))
        or 0
    )
    events = db.scalars(select(TradeEvent).order_by(TradeEvent.id.desc()).limit(10))
    return {
        "accounts": per_account,
        "currency": currency,
        "totals": {
            "balance": ser.d(sum((a.balance or Decimal(0) for a in accounts), Decimal(0)))
            if accounts
            else None,
            "equity": ser.d(sum((a.equity or Decimal(0) for a in accounts), Decimal(0)))
            if accounts
            else None,
            "today_pnl": ser.d(Decimal(str(closed_today or 0)) + open_pnl) if accounts else None,
            "realized_today": ser.d(Decimal(str(closed_today or 0))) if accounts else None,
            "open_pnl": ser.d(open_pnl) if accounts else None,
            "open_positions": len(open_trades),
            "trades_today": int(trades_today or 0),
            "open_risk": ser.d(open_risk) if accounts else None,
            "open_risk_unknown": unknown_risk,
            "max_drawdown_pct": max((a["drawdown_pct"] or 0 for a in per_account), default=None),
        },
        "active_strategies": active,
        "equity_series": equity_series,
        "equity_series_account": str(accounts[0].id) if accounts else None,
        "recent_events": [ser.event(e) for e in events],
    }
