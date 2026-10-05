"""Order submission, position closing/modification, and fill bookkeeping."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import (
    BrokerConnectionError,
    BrokerError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import (
    Deal,
    DealEntry,
    OrderHint,
    OrderRequest,
    OrderResult,
    Quote,
)
from fxrobot.db.types import utcnow
from fxrobot.domain.market import Side, SymbolInfo
from fxrobot.domain.trading import (
    ExitReason,
    OrderPurpose,
    OrderStatus,
    OrderType,
    SignalStatus,
    TradeStatus,
)
from fxrobot.execution_engine import journal
from fxrobot.execution_engine.ids import new_client_order_id
from fxrobot.execution_engine.journal import EventType
from fxrobot.market_data.sessions import session_at
from fxrobot.models import Order, Signal, Trade, TradingAccount
from fxrobot.notifications.service import notify
from fxrobot.risk_engine.engine import RiskDecision

logger = logging.getLogger(__name__)

DEAL_REASON_TO_EXIT = {
    "SL": ExitReason.STOP_LOSS,
    "TP": ExitReason.TAKE_PROFIT,
    "SO": ExitReason.EMERGENCY,
    "CLIENT": ExitReason.MANUAL,
}


def _v(value: Decimal | None) -> str:
    """Human volume, e.g. 0.09 rather than the DB's 0.0900."""
    return "—" if value is None else format(value.normalize(), "f")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


class ExecutionEngine:
    """Stateless; every method works inside the caller's DB session."""

    # ── entries ──────────────────────────────────────────────────────────
    def submit_entry(
        self,
        db: Session,
        *,
        account: TradingAccount,
        signal: Signal,
        decision: RiskDecision,
        adapter: BrokerAdapter,
        symbol: SymbolInfo,
        quote: Quote,
    ) -> Order:
        if not decision.approved or decision.volume is None:
            raise ValueError("only approved risk decisions can be executed")
        order = Order(
            client_order_id=new_client_order_id(),
            account_id=account.id,
            signal_id=signal.id,
            purpose=OrderPurpose.ENTRY,
            symbol=signal.symbol,
            side=signal.side,
            order_type=OrderType.MARKET,
            volume=decision.volume,
            requested_price=quote.ask if signal.side is Side.BUY else quote.bid,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status=OrderStatus.PENDING_SUBMIT,
            is_simulated=adapter.is_simulated,
        )
        db.add(order)
        db.commit()  # crash-safe intent: the order exists before anything is sent
        order.status = OrderStatus.SUBMITTED
        order.attempts += 1
        order.submitted_at = utcnow()
        journal.record(
            db,
            EventType.ORDER_SUBMITTED,
            f"{'PAPER ' if adapter.is_simulated else ''}{signal.side.value} {_v(decision.volume)} "
            f"{signal.symbol} @ market (SL {signal.stop_loss}, TP {signal.take_profit})",
            account_id=account.id,
            signal_id=signal.id,
            order_id=order.id,
            data={
                "client_order_id": order.client_order_id,
                "requested_price": str(order.requested_price),
                "risk_amount": str(decision.risk_amount),
                "simulated": adapter.is_simulated,
            },
        )
        db.commit()
        notify(
            db,
            "order.submitted",
            f"{'PAPER ' if adapter.is_simulated else ''}{signal.side.value} {_v(decision.volume)} "
            f"{signal.symbol} submitted.",
            account_id=account.id,
            data={"order_id": str(order.id)},
        )
        request = OrderRequest(
            client_order_id=order.client_order_id,
            symbol=signal.symbol,
            side=signal.side,
            order_type=OrderType.MARKET,
            volume=decision.volume,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            max_slippage_points=decision.max_slippage_points,
            comment="2kFX",
        )
        try:
            result = adapter.place_order(request)
        except OrderRejectedError as exc:
            self._rejected(db, order, signal, exc)
            return order
        except BrokerConnectionError as exc:
            # The adapter could not send it: definitely not executed.
            self._failed(db, order, signal, f"Not sent: {exc}")
            return order
        except OrderOutcomeUnknownError as exc:
            self._unknown(db, order, str(exc))
            self.reconcile_order(db, order, adapter, symbol=symbol)
            return order
        except BrokerError as exc:
            # Anything else during a trade call is treated as uncertain.
            self._unknown(db, order, f"{exc.__class__.__name__}: {exc}")
            self.reconcile_order(db, order, adapter, symbol=symbol)
            return order
        self.apply_result(db, order, result, adapter=adapter, symbol=symbol, quote=quote)
        return order

    def _rejected(self, db: Session, order: Order, signal: Signal | None, exc: BrokerError) -> None:
        order.status = OrderStatus.REJECTED
        order.broker_code = exc.broker_code or exc.code
        order.broker_message = str(exc)[:500]
        if signal is not None:
            signal.status = SignalStatus.FAILED
            signal.rejection_reason = f"Broker rejected: {exc}"[:500]
        journal.record(
            db,
            EventType.ORDER_REJECTED,
            f"Order rejected by broker: {exc}",
            account_id=order.account_id,
            signal_id=order.signal_id,
            order_id=order.id,
            data={"code": order.broker_code},
        )
        db.commit()
        notify(
            db,
            "order.rejected",
            f"{order.side.value} {_v(order.volume)} {order.symbol}: {exc}",
            account_id=order.account_id,
        )

    def _failed(self, db: Session, order: Order, signal: Signal | None, message: str) -> None:
        order.status = OrderStatus.FAILED
        order.broker_message = message[:500]
        if signal is not None:
            signal.status = SignalStatus.FAILED
            signal.rejection_reason = message[:500]
        journal.record(
            db,
            EventType.ORDER_FAILED,
            message,
            account_id=order.account_id,
            signal_id=order.signal_id,
            order_id=order.id,
        )
        db.commit()
        notify(db, "order.rejected", f"{order.symbol}: {message}", account_id=order.account_id)

    def _unknown(self, db: Session, order: Order, message: str) -> None:
        order.status = OrderStatus.UNKNOWN
        order.broker_message = message[:500]
        journal.record(
            db,
            EventType.ORDER_UNKNOWN,
            f"Outcome uncertain ({message}). Will reconcile with the broker; "
            "the order will NOT be re-sent.",
            account_id=order.account_id,
            signal_id=order.signal_id,
            order_id=order.id,
        )
        db.commit()
        notify(
            db,
            "order.unknown",
            f"{order.side.value} {_v(order.volume)} {order.symbol}: "
            "outcome uncertain — reconciling.",
            account_id=order.account_id,
        )

    # ── results & reconciliation ─────────────────────────────────────────
    def apply_result(
        self,
        db: Session,
        order: Order,
        result: OrderResult,
        *,
        adapter: BrokerAdapter,
        symbol: SymbolInfo | None = None,
        quote: Quote | None = None,
    ) -> None:
        order.broker_order_id = result.broker_order_id or order.broker_order_id
        order.broker_position_id = result.broker_position_id or order.broker_position_id
        order.broker_code = result.broker_code
        order.broker_message = (result.broker_message or "")[:500] or None
        signal = db.get(Signal, order.signal_id) if order.signal_id else None
        if result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            order.status = result.status
            order.filled_volume = result.filled_volume or order.volume
            order.fill_price = result.fill_price
            order.filled_at = result.time or adapter.now()
            if order.purpose is OrderPurpose.ENTRY:
                self.open_trade(db, order, signal, adapter=adapter, symbol=symbol, quote=quote)
            db.commit()
        elif result.status is OrderStatus.PENDING:
            order.status = OrderStatus.PENDING
            journal.record(
                db,
                EventType.ORDER_PENDING,
                "Order resting at broker",
                account_id=order.account_id,
                order_id=order.id,
            )
            db.commit()
        elif result.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            order.status = result.status
            if signal is not None and signal.status is not SignalStatus.EXECUTED:
                signal.status = SignalStatus.FAILED
                signal.rejection_reason = (result.broker_message or result.status.value)[:500]
            journal.record(
                db,
                EventType.ORDER_REJECTED,
                f"Order {result.status.value.lower()}: {result.broker_message}",
                account_id=order.account_id,
                order_id=order.id,
            )
            db.commit()
        else:
            order.status = OrderStatus.UNKNOWN
            db.commit()

    def open_trade(
        self,
        db: Session,
        order: Order,
        signal: Signal | None,
        *,
        adapter: BrokerAdapter,
        symbol: SymbolInfo | None,
        quote: Quote | None,
    ) -> Trade:
        existing = None
        if order.broker_position_id:
            existing = (
                db.query(Trade)
                .filter_by(account_id=order.account_id, broker_position_id=order.broker_position_id)
                .first()
            )
        if existing is not None:
            return existing
        fill = order.fill_price or order.requested_price or Decimal(0)
        slippage = None
        if (
            symbol is not None
            and order.requested_price is not None
            and order.fill_price is not None
        ):
            adverse = (order.fill_price - order.requested_price) * order.side.sign
            slippage = (adverse / symbol.pip_size).quantize(Decimal("0.1")) + Decimal(
                0
            )  # no "-0.0"
        entry_time = order.filled_at or adapter.now()
        trade = Trade(
            account_id=order.account_id,
            signal_id=order.signal_id,
            strategy_version_id=signal.strategy_version_id if signal else None,
            symbol=order.symbol,
            side=order.side,
            status=TradeStatus.OPEN,
            volume=order.filled_volume or order.volume,
            requested_entry=signal.entry_price if signal else order.requested_price,
            entry_price=fill,
            entry_time=entry_time,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            initial_stop_loss=order.stop_loss,
            risk_amount=signal.risk_amount if signal else None,
            spread_at_entry=quote.spread if quote else None,
            slippage_pips=slippage,
            session=session_at(entry_time).value,
            broker_position_id=order.broker_position_id,
            is_simulated=order.is_simulated,
            commission=Decimal(0),
            swap=Decimal(0),
        )
        db.add(trade)
        db.flush()
        order.trade_id = trade.id
        if signal is not None:
            signal.status = SignalStatus.EXECUTED
        prefix = "PAPER " if order.is_simulated else ""
        journal.record(
            db,
            EventType.ORDER_FILLED,
            f"{prefix}Filled {_v(order.filled_volume)} {order.symbol} at {fill}"
            + (f" (slippage {slippage} pips)" if slippage is not None else ""),
            account_id=order.account_id,
            signal_id=order.signal_id,
            order_id=order.id,
            trade_id=trade.id,
            data={"fill_price": str(fill), "simulated": order.is_simulated},
        )
        journal.record(
            db,
            EventType.POSITION_OPENED,
            f"{prefix}{order.side.value} {_v(trade.volume)} {order.symbol} opened at {fill}",
            account_id=order.account_id,
            signal_id=order.signal_id,
            order_id=order.id,
            trade_id=trade.id,
        )
        db.commit()
        notify(
            db,
            "position.opened",
            f"{prefix}{order.side.value} {_v(trade.volume)} {order.symbol} at {fill}",
            account_id=order.account_id,
            data={"trade_id": str(trade.id)},
        )
        return trade

    def reconcile_order(
        self,
        db: Session,
        order: Order,
        adapter: BrokerAdapter,
        *,
        symbol: SymbolInfo | None = None,
        grace: timedelta = timedelta(minutes=2),
    ) -> bool:
        """Resolve an order whose outcome is uncertain. Returns True if resolved."""
        try:
            hint = OrderHint(order.symbol, order.side, order.volume, order.submitted_at)
            found = adapter.find_order_by_client_id(order.client_order_id, hint)
        except BrokerError as exc:
            logger.warning("reconciliation lookup failed for %s: %s", order.client_order_id, exc)
            return False
        order.last_reconciled_at = utcnow()
        if found is not None:
            journal.record(
                db,
                EventType.ORDER_RECONCILED,
                f"Broker confirms order {order.client_order_id}: {found.status.value}",
                account_id=order.account_id,
                order_id=order.id,
            )
            self.apply_result(db, order, found, adapter=adapter, symbol=symbol)
            return True
        reference = order.submitted_at or order.created_at
        if order.status is OrderStatus.PENDING_SUBMIT or (
            reference is not None and utcnow() - reference > grace
        ):
            signal = db.get(Signal, order.signal_id) if order.signal_id else None
            self._failed(
                db, order, signal, "Broker has no record of this order — it was not executed."
            )
            return True
        db.commit()
        return False

    # ── exits & modifications ────────────────────────────────────────────
    def close_trade(
        self,
        db: Session,
        trade: Trade,
        adapter: BrokerAdapter,
        *,
        reason: ExitReason,
        note: str = "",
    ) -> Order:
        if trade.status is not TradeStatus.OPEN or not trade.broker_position_id:
            raise ValueError("trade is not open at the broker")
        order = Order(
            client_order_id=new_client_order_id(),
            account_id=trade.account_id,
            trade_id=trade.id,
            purpose=OrderPurpose.EXIT,
            symbol=trade.symbol,
            side=trade.side.opposite,
            order_type=OrderType.MARKET,
            volume=trade.volume,
            status=OrderStatus.PENDING_SUBMIT,
            is_simulated=adapter.is_simulated,
        )
        db.add(order)
        db.commit()
        order.status, order.attempts, order.submitted_at = OrderStatus.SUBMITTED, 1, utcnow()
        journal.record(
            db,
            EventType.ORDER_SUBMITTED,
            f"Close {trade.side.value} {_v(trade.volume)} {trade.symbol} "
            f"({reason.value}) {note}".strip(),
            account_id=trade.account_id,
            order_id=order.id,
            trade_id=trade.id,
        )
        db.commit()
        try:
            result = adapter.close_position(trade.broker_position_id, order.client_order_id)
        except OrderRejectedError as exc:
            self._rejected(db, order, None, exc)
            return order
        except BrokerConnectionError as exc:
            self._failed(db, order, None, f"Not sent: {exc}")
            return order
        except BrokerError as exc:
            self._unknown(db, order, str(exc))
            self.reconcile_order(db, order, adapter)
            return order
        self.apply_result(db, order, result, adapter=adapter)
        if order.status is OrderStatus.FILLED:
            self.finalize_trade(
                db, trade, adapter, fallback_price=order.fill_price, fallback_reason=reason
            )
        return order

    def modify_trade(
        self,
        db: Session,
        trade: Trade,
        adapter: BrokerAdapter,
        *,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
        actor: str,
    ) -> None:
        if trade.status is not TradeStatus.OPEN or not trade.broker_position_id:
            raise ValueError("trade is not open at the broker")
        if stop_loss is None:
            raise ValueError("a stop loss is mandatory")
        adapter.modify_position(trade.broker_position_id, stop_loss, take_profit)
        old = {"stop_loss": str(trade.stop_loss), "take_profit": str(trade.take_profit)}
        trade.stop_loss, trade.take_profit = stop_loss, take_profit
        journal.record(
            db,
            EventType.POSITION_MODIFIED,
            f"SL {old['stop_loss']} → {stop_loss}, "
            f"TP {old['take_profit']} → {take_profit} by {actor}",
            account_id=trade.account_id,
            trade_id=trade.id,
            data={"before": old, "actor": actor},
        )
        db.commit()

    def finalize_trade(
        self,
        db: Session,
        trade: Trade,
        adapter: BrokerAdapter,
        *,
        fallback_price: Decimal | None = None,
        fallback_reason: ExitReason = ExitReason.BROKER,
        deals: list[Deal] | None = None,
    ) -> None:
        """Record the exit of a trade using the broker's deal history when available."""
        if trade.status is TradeStatus.CLOSED:
            return
        now = adapter.now()
        if deals is None:
            try:
                deals = adapter.get_deals(
                    trade.entry_time - timedelta(days=1), now + timedelta(minutes=5)
                )
            except BrokerError:
                deals = []
        position_deals = [d for d in deals if d.position_id == trade.broker_position_id]
        exits = [d for d in position_deals if d.entry in (DealEntry.OUT, DealEntry.INOUT)]
        entries = [d for d in position_deals if d.entry is DealEntry.IN]
        if exits:
            volume = sum((d.volume for d in exits), Decimal(0))
            price = sum((d.price * d.volume for d in exits), Decimal(0)) / volume
            gross = sum((d.profit for d in exits), Decimal(0))
            commission = sum((d.commission + d.fee for d in exits + entries), Decimal(0))
            swap = sum((d.swap for d in exits), Decimal(0))
            reason = DEAL_REASON_TO_EXIT.get(exits[-1].reason, fallback_reason)
            if fallback_reason in (ExitReason.MANUAL, ExitReason.EMERGENCY, ExitReason.STRATEGY):
                reason = fallback_reason
            exit_time = exits[-1].time
        else:
            price = fallback_price if fallback_price is not None else trade.entry_price
            gross, commission, swap, reason, exit_time = (
                None,
                Decimal(0),
                Decimal(0),
                fallback_reason,
                now,
            )
            journal.record(
                db,
                EventType.POSITION_CLOSED,
                "Closing deal not found in broker history — P/L unknown",
                account_id=trade.account_id,
                trade_id=trade.id,
            )
        trade.status = TradeStatus.CLOSED
        trade.exit_price, trade.exit_time, trade.exit_reason = price, exit_time, reason
        trade.gross_pnl = _money(gross) if gross is not None else None
        trade.commission, trade.swap = _money(commission), _money(swap)
        trade.net_pnl = _money(gross + commission + swap) if gross is not None else None
        trade.unrealized_pnl = None
        if trade.net_pnl is not None and trade.risk_amount:
            trade.r_multiple = (trade.net_pnl / trade.risk_amount).quantize(Decimal("0.01"))
        prefix = "PAPER " if trade.is_simulated else ""
        journal.record(
            db,
            EventType.POSITION_CLOSED,
            f"{prefix}{trade.side.value} {_v(trade.volume)} {trade.symbol} closed at {price} "
            f"({reason.value}), net P/L {trade.net_pnl}",
            account_id=trade.account_id,
            trade_id=trade.id,
            data={"exit_price": str(price), "net_pnl": str(trade.net_pnl), "reason": reason.value},
        )
        db.commit()
        kind = {
            ExitReason.STOP_LOSS: "position.stop_loss",
            ExitReason.TAKE_PROFIT: "position.take_profit",
        }.get(reason, "position.closed")
        notify(
            db,
            kind,
            f"{prefix}{trade.symbol} {trade.side.value} closed at {price}: net {trade.net_pnl}",
            account_id=trade.account_id,
            data={"trade_id": str(trade.id)},
        )


def order_summary(order: Order) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "status": order.status.value,
        "symbol": order.symbol,
        "side": order.side.value,
        "volume": str(order.volume),
    }


def since(moment: datetime, **delta: float) -> datetime:
    return moment - timedelta(**delta)
