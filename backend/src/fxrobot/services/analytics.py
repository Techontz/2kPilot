"""Live/paper analytics — computed only from stored real records, never invented."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.analytics import metrics
from fxrobot.domain.trading import OrderPurpose, OrderStatus, SignalStatus, TradeStatus
from fxrobot.models import (
    AccountSnapshot,
    Order,
    Signal,
    Strategy,
    StrategyVersion,
    Trade,
    TradingAccount,
)


def _accounts(db: Session, account_id: uuid.UUID | None) -> list[TradingAccount]:
    stmt = select(TradingAccount)
    if account_id is not None:
        stmt = stmt.where(TradingAccount.id == account_id)
    return list(db.scalars(stmt))


def performance(
    db: Session, account_id: uuid.UUID | None, since: datetime | None
) -> dict[str, Any]:
    accounts = _accounts(db, account_id)
    ids = [a.id for a in accounts]
    if not ids:
        return {"has_data": False, "accounts": []}
    stmt = (
        select(Trade, Strategy.name)
        .outerjoin(StrategyVersion, Trade.strategy_version_id == StrategyVersion.id)
        .outerjoin(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .where(
            Trade.account_id.in_(ids),
            Trade.status == TradeStatus.CLOSED,
            Trade.net_pnl.is_not(None),
        )
    )
    if since is not None:
        stmt = stmt.where(Trade.exit_time >= since)
    rows = db.execute(stmt.order_by(Trade.exit_time)).all()
    stats = [
        metrics.TradeStat(
            net_pnl=t.net_pnl or Decimal(0),
            entry_time=t.entry_time,
            exit_time=t.exit_time or t.entry_time,
            symbol=t.symbol,
            side=t.side.value,
            session=t.session or "—",
            r_multiple=t.r_multiple,
            costs=-(t.commission + t.swap),
            strategy=name or "Manual / external",
        )
        for t, name in rows
    ]
    snap_stmt = (
        select(AccountSnapshot)
        .where(AccountSnapshot.account_id.in_(ids))
        .order_by(AccountSnapshot.taken_at)
    )
    if since is not None:
        snap_stmt = snap_stmt.where(AccountSnapshot.taken_at >= since)
    snapshots = list(db.scalars(snap_stmt))
    # Combine accounts' equity by summing the latest snapshot of each at every timestamp.
    latest: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    equity_points: list[tuple[datetime, Decimal]] = []
    balance_points: list[dict[str, Any]] = []
    for s in snapshots:
        latest[s.account_id] = (s.balance, s.equity)
        eq = sum((v[1] for v in latest.values()), Decimal(0))
        bal = sum((v[0] for v in latest.values()), Decimal(0))
        equity_points.append((s.taken_at, eq))
        balance_points.append(
            {"t": s.taken_at.isoformat(), "balance": float(bal), "equity": float(eq)}
        )
    starting = (
        equity_points[0][1]
        if equity_points
        else sum(((a.balance or Decimal(0)) for a in accounts), Decimal(0))
        - sum((s.net_pnl for s in stats), Decimal(0))
    )
    report = metrics.compute(stats, starting if starting > 0 else Decimal(1), equity_points or None)
    open_trades = list(
        db.scalars(select(Trade).where(Trade.account_id.in_(ids), Trade.status == TradeStatus.OPEN))
    )
    report["unrealized_pnl"] = float(
        sum((t.unrealized_pnl or Decimal(0) for t in open_trades), Decimal(0))
    )
    report["open_positions"] = len(open_trades)
    report["balance_history"] = metrics.downsample(balance_points)
    report["daily"] = _periodic(stats, "%Y-%m-%d")
    report["weekly"] = _periodic(stats, "%G-W%V")
    report["execution"] = execution_quality(db, ids, since)
    report["has_data"] = bool(stats or snapshots)
    report["simulated"] = all(a.environment.value == "PAPER" for a in accounts)
    return report


def _periodic(stats: list[metrics.TradeStat], fmt: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[Decimal]] = defaultdict(list)
    for s in stats:
        buckets[s.exit_time.strftime(fmt)].append(s.net_pnl)
    return [
        {"period": k, "net_pnl": float(sum(v, Decimal(0))), "trades": len(v)}
        for k, v in sorted(buckets.items())
    ][-120:]


def execution_quality(db: Session, ids: list[uuid.UUID], since: datetime | None) -> dict[str, Any]:
    stmt = select(Order).where(Order.account_id.in_(ids), Order.purpose == OrderPurpose.ENTRY)
    if since is not None:
        stmt = stmt.where(Order.created_at >= since)
    orders = list(db.scalars(stmt))
    by_status: dict[str, int] = defaultdict(int)
    for o in orders:
        by_status[o.status.value] += 1
    trade_stmt = select(Trade).where(Trade.account_id.in_(ids), Trade.slippage_pips.is_not(None))
    if since is not None:
        trade_stmt = trade_stmt.where(Trade.entry_time >= since)
    trades = list(db.scalars(trade_stmt))
    slippage = [float(t.slippage_pips) for t in trades if t.slippage_pips is not None]
    spreads = [float(t.spread_at_entry) for t in trades if t.spread_at_entry is not None]
    latency = [
        (o.filled_at - o.submitted_at).total_seconds()
        for o in orders
        if o.filled_at and o.submitted_at and o.filled_at >= o.submitted_at
    ]
    sig_stmt = (
        select(Signal.status, func.count())
        .where(Signal.account_id.in_(ids))
        .group_by(Signal.status)
    )
    signals = {status.value: count for status, count in db.execute(sig_stmt).all()}
    rejected_reasons = db.execute(
        select(Signal.rejection_reason, func.count())
        .where(Signal.account_id.in_(ids), Signal.status == SignalStatus.REJECTED)
        .group_by(Signal.rejection_reason)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    filled = by_status.get("FILLED", 0) + by_status.get("PARTIALLY_FILLED", 0)
    return {
        "orders": len(orders),
        "orders_by_status": dict(by_status),
        "fill_rate": round(filled / len(orders) * 100, 1) if orders else None,
        "avg_slippage_pips": round(sum(slippage) / len(slippage), 2) if slippage else None,
        "worst_slippage_pips": round(max(slippage), 2) if slippage else None,
        "avg_spread": round(sum(spreads) / len(spreads), 6) if spreads else None,
        "avg_fill_seconds": round(sum(latency) / len(latency), 2) if latency else None,
        "unresolved_orders": sum(
            by_status.get(s.value, 0)
            for s in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTED, OrderStatus.PENDING_SUBMIT)
        ),
        "signals_by_status": signals,
        "top_rejections": [{"reason": r or "—", "count": c} for r, c in rejected_reasons],
    }
