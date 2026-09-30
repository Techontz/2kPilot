"""LIVE readiness checklist.

The checklist never unlocks anything: LIVE stays impossible while the server
hard lock (LIVE_TRADING_ENABLED=false) is on. It gathers the evidence a human
needs for the deliberate Phase-10 review.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.config import Settings
from fxrobot.core.errors import NotFoundError
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import (
    AssignmentStatus,
    BacktestKind,
    BacktestStatus,
    ConnectionStatus,
    EngineState,
    OrderStatus,
    TradeStatus,
)
from fxrobot.models import (
    AuditLog,
    Backtest,
    BrokerConnection,
    Order,
    StrategyAssignment,
    Trade,
    TradingAccount,
)
from fxrobot.services import trading_control

MIN_DEMO_TRADES = 30
MIN_DEMO_DAYS = 28
MIN_OOS_TRADES = 30


@dataclass
class Item:
    id: str
    label: str
    passed: bool
    detail: str
    required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def checklist(
    db: Session, account_id: uuid.UUID, settings: Settings, manager: BrokerManager
) -> dict[str, Any]:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    connection = db.get(BrokerConnection, account.connection_id)
    items: list[Item] = []
    status = trading_control.get_status(db, settings)

    items.append(
        Item(
            "live_lock",
            "Server LIVE lock",
            not status.live_trading_locked,
            "LIVE_TRADING_ENABLED=false — LIVE is impossible until an operator changes it"
            if status.live_trading_locked
            else "Unlocked by the operator",
        )
    )
    connected = connection is not None and connection.status is ConnectionStatus.CONNECTED
    items.append(
        Item(
            "broker_connected",
            "Broker connected",
            connected,
            connection.status_detail or connection.status.value if connection else "missing",
        )
    )
    items.append(
        Item(
            "account_recognized",
            "Account recognised as LIVE by the broker",
            account.environment is AccountEnvironment.LIVE,
            f"broker reports {account.environment.value}",
        )
    )
    items.append(
        Item(
            "risk_profile",
            "Risk profile configured",
            account.risk_profile_id is not None,
            "assigned" if account.risk_profile_id else "no risk profile",
        )
    )
    engaged_before = (
        db.scalar(select(func.count()).where(AuditLog.action == "trading.kill_switch.engaged")) or 0
    )
    items.append(
        Item(
            "kill_switch",
            "Kill switch tested",
            engaged_before > 0,
            f"engaged {engaged_before} time(s); currently "
            f"{'engaged' if status.state.kill_switch_engaged else 'released'}",
        )
    )
    assignments = list(
        db.scalars(select(StrategyAssignment).where(StrategyAssignment.account_id == account.id))
    )
    items.append(
        Item(
            "strategy",
            "Strategy configured",
            bool(assignments),
            f"{len(assignments)} assignment(s), "
            f"{sum(a.status is AssignmentStatus.ENABLED for a in assignments)} enabled",
        )
    )
    version_ids = {a.strategy_version_id for a in assignments}
    validated = db.scalars(
        select(Backtest).where(
            Backtest.strategy_version_id.in_(version_ids) if version_ids else Backtest.id.is_(None),
            Backtest.kind.in_([BacktestKind.SPLIT, BacktestKind.WALK_FORWARD]),
            Backtest.status == BacktestStatus.COMPLETED,
        )
    ).all()
    good = [
        b
        for b in validated
        if (b.metrics or {}).get("trades", 0) >= MIN_OOS_TRADES
        and ((b.metrics or {}).get("expectancy_r") or 0) > 0
        and b.data_source != "synthetic"
    ]
    items.append(
        Item(
            "oos_validation",
            "Out-of-sample validation on real data",
            bool(good),
            f"{len(good)} qualifying run(s) (≥{MIN_OOS_TRADES} trades, positive expectancy, "
            "non-synthetic data)",
        )
    )
    demo_ids = list(
        db.scalars(
            select(TradingAccount.id).where(TradingAccount.environment == AccountEnvironment.DEMO)
        )
    )
    demo_trades = list(
        db.scalars(
            select(Trade)
            .where(
                Trade.account_id.in_(demo_ids) if demo_ids else Trade.id.is_(None),
                Trade.status == TradeStatus.CLOSED,
            )
            .order_by(Trade.entry_time)
        )
    )
    span = (
        (demo_trades[-1].exit_time - demo_trades[0].entry_time)
        if len(demo_trades) > 1 and demo_trades[-1].exit_time
        else timedelta(0)
    )
    demo_ok = len(demo_trades) >= MIN_DEMO_TRADES and span >= timedelta(days=MIN_DEMO_DAYS)
    items.append(
        Item(
            "demo_record",
            "Broker DEMO track record",
            demo_ok,
            f"{len(demo_trades)} closed demo trades over {span.days} days "
            f"(need {MIN_DEMO_TRADES} over {MIN_DEMO_DAYS}+ days)",
        )
    )
    data_ok, data_detail = False, "broker not connected"
    if connected and connection is not None:
        try:
            adapter = manager.get(connection.id)
            symbol = assignments[0].symbol if assignments else None
            if symbol:
                quote = adapter.get_quote(symbol)
                age = (adapter.now() - quote.time).total_seconds()
                data_ok, data_detail = age <= 120, f"{symbol} quote {int(age)}s old"
            else:
                data_detail = "no strategy symbol to check"
        except BrokerError as exc:
            data_detail = str(exc)
    items.append(Item("market_data", "Market data valid", data_ok, data_detail))
    recent = list(
        db.scalars(
            select(Order)
            .where(Order.account_id.in_([*demo_ids, account.id]))
            .order_by(Order.created_at.desc())
            .limit(50)
        )
    )
    unknown = sum(o.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTED) for o in recent)
    failed = sum(o.status in (OrderStatus.FAILED, OrderStatus.REJECTED) for o in recent)
    exec_ok = bool(recent) and unknown == 0 and failed / len(recent) < 0.1
    items.append(
        Item(
            "execution",
            "Execution path healthy",
            exec_ok,
            f"last {len(recent)} orders: {failed} failed/rejected, {unknown} unresolved"
            if recent
            else "no orders yet",
        )
    )
    items.append(
        Item(
            "engine",
            "Trading engine running",
            status.engine_state is not EngineState.OFFLINE,
            status.engine_detail,
        )
    )
    items.append(
        Item(
            "mfa",
            "Owner MFA enabled",
            False,
            "Not implemented yet — required before any live deployment",
            required=True,
        )
    )
    required = [i for i in items if i.required]
    return {
        "account_id": str(account.id),
        "checked_at": utcnow().isoformat(),
        "ready": all(i.passed for i in required),
        "passed": sum(i.passed for i in required),
        "total": len(required),
        "items": [i.as_dict() for i in items],
        "note": "Passing every check does not enable LIVE. Unlocking requires the operator to "
        "set LIVE_TRADING_ENABLED=true on the server after a deliberate review.",
    }
