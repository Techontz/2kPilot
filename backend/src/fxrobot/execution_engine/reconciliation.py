"""Keep the database's view of orders and positions consistent with the broker.

Runs on every engine tick for every connected account, and on startup
before any new signal is processed (restart recovery).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.domain.trading import ExitReason, OrderPurpose, OrderStatus, TradeStatus
from fxrobot.execution_engine import journal
from fxrobot.execution_engine.engine import ExecutionEngine
from fxrobot.execution_engine.journal import EventType
from fxrobot.market_data.sessions import session_at
from fxrobot.models import Order, Signal, Trade, TradingAccount
from fxrobot.notifications.service import notify

logger = logging.getLogger(__name__)

UNRESOLVED = (OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED, OrderStatus.UNKNOWN)


@dataclass
class ReconcileReport:
    orders_resolved: int = 0
    orders_unresolved: int = 0
    trades_closed: int = 0
    trades_recovered: int = 0
    external_positions: int = 0
    notes: list[str] = field(default_factory=list)


def unresolved_orders(db: Session, account_id: object) -> list[Order]:
    return list(
        db.scalars(
            select(Order).where(Order.account_id == account_id, Order.status.in_(UNRESOLVED))
        )
    )


def reconcile_account(
    db: Session, account: TradingAccount, adapter: BrokerAdapter, execution: ExecutionEngine
) -> ReconcileReport:
    report = ReconcileReport()
    for order in unresolved_orders(db, account.id):
        if execution.reconcile_order(db, order, adapter):
            report.orders_resolved += 1
        else:
            report.orders_unresolved += 1
    try:
        positions = adapter.get_positions()
    except BrokerError as exc:
        report.notes.append(f"positions unavailable: {exc}")
        return report
    by_id = {p.position_id: p for p in positions}
    open_trades = list(
        db.scalars(
            select(Trade).where(Trade.account_id == account.id, Trade.status == TradeStatus.OPEN)
        )
    )
    tracked = {t.broker_position_id for t in open_trades}

    # 1. Trades we think are open but the broker has closed (SL/TP/stop-out/manual).
    missing = [t for t in open_trades if t.broker_position_id not in by_id]
    if missing:
        try:
            earliest = min(t.entry_time for t in missing) - timedelta(days=1)
            deals = adapter.get_deals(earliest, adapter.now() + timedelta(minutes=5))
        except BrokerError as exc:
            report.notes.append(f"deal history unavailable: {exc}")
            deals = None
        if deals is not None:
            for trade in missing:
                exit_order = db.scalar(
                    select(Order).where(
                        Order.trade_id == trade.id,
                        Order.purpose == OrderPurpose.EXIT,
                        Order.status == OrderStatus.FILLED,
                    )
                )
                reason = ExitReason.MANUAL if exit_order else ExitReason.BROKER
                execution.finalize_trade(
                    db,
                    trade,
                    adapter,
                    deals=deals,
                    fallback_reason=reason,
                    fallback_price=exit_order.fill_price if exit_order else None,
                )
                report.trades_closed += 1

    # 2. Broker positions we are not tracking: recovery (our order) or external.
    for position in positions:
        if position.position_id in tracked:
            continue
        ours: Order | None = None
        if position.client_order_id:
            ours = db.scalar(select(Order).where(Order.client_order_id == position.client_order_id))
        if ours is not None:
            # Restart recovery: the broker holds a position from one of OUR orders.
            ours.broker_position_id = position.position_id
            # FAILED was only our inference ("broker has no record"); the position proves
            # the order executed, so correct it rather than leave a FAILED order with a trade.
            if ours.status in UNRESOLVED or ours.status is OrderStatus.FAILED:
                if ours.status is OrderStatus.FAILED:
                    journal.record(
                        db,
                        EventType.ORDER_RECONCILED,
                        f"Order {ours.client_order_id} was marked failed, but the broker "
                        f"holds its position {position.position_id}: corrected to FILLED.",
                        account_id=account.id,
                        signal_id=ours.signal_id,
                        order_id=ours.id,
                    )
                ours.status = OrderStatus.FILLED
                ours.filled_volume = position.volume
                ours.fill_price = position.open_price
                ours.filled_at = position.open_time
            signal = db.get(Signal, ours.signal_id) if ours.signal_id else None
            if signal is not None:
                signal.rejection_reason = None  # the earlier "not executed" inference was wrong
            execution.open_trade(db, ours, signal, adapter=adapter, symbol=None, quote=None)
            report.trades_recovered += 1
            continue
        trade = Trade(
            account_id=account.id,
            symbol=position.symbol,
            side=position.side,
            status=TradeStatus.OPEN,
            volume=position.volume,
            entry_price=position.open_price,
            entry_time=position.open_time,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            initial_stop_loss=position.stop_loss,
            broker_position_id=position.position_id,
            session=session_at(position.open_time).value,
            is_simulated=adapter.is_simulated,
            commission=Decimal(0),
            swap=Decimal(0),
        )
        db.add(trade)
        db.flush()
        journal.record(
            db,
            EventType.EXTERNAL_POSITION,
            f"Position {position.position_id} ({position.side.value} {position.volume} "
            f"{position.symbol}) was opened outside 2kFX. It is tracked, and its "
            "unknown risk blocks new entries until it is closed.",
            account_id=account.id,
            trade_id=trade.id,
        )
        db.commit()
        notify(
            db,
            "reconciliation.mismatch",
            f"{account.label}: found a position opened outside 2kFX ({position.symbol}).",
            account_id=account.id,
        )
        report.external_positions += 1

    # 3. Keep open trades in sync (SL/TP edits in the terminal, partial closes, P/L).
    for trade in open_trades:
        live = by_id.get(trade.broker_position_id or "")
        if live is None or trade.status is not TradeStatus.OPEN:
            continue
        changed = []
        if live.stop_loss != trade.stop_loss or live.take_profit != trade.take_profit:
            changed.append(
                f"SL {trade.stop_loss}→{live.stop_loss}, TP {trade.take_profit}→{live.take_profit}"
            )
            trade.stop_loss, trade.take_profit = live.stop_loss, live.take_profit
        if live.volume != trade.volume:
            changed.append(f"volume {trade.volume}→{live.volume}")
            trade.volume = live.volume
        trade.unrealized_pnl = live.unrealized_pnl
        trade.swap = live.swap
        if changed:
            journal.record(
                db,
                EventType.POSITION_MODIFIED,
                "Changed at the broker: " + "; ".join(changed),
                account_id=account.id,
                trade_id=trade.id,
            )
    db.commit()
    return report
