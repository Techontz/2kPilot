"""Per-account pipeline: one tick = advance → reconcile → sync → strategies → risk → execution."""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerConnectionError, BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.broker_engine.models import AccountInfo
from fxrobot.core.context import new_correlation_id, set_correlation_id
from fxrobot.core.events import bus
from fxrobot.db.types import utcnow
from fxrobot.domain.market import Candle, Timeframe
from fxrobot.domain.trading import AssignmentStatus, SignalStatus
from fxrobot.execution_engine import journal
from fxrobot.execution_engine.engine import ExecutionEngine
from fxrobot.execution_engine.journal import EventType
from fxrobot.execution_engine.reconciliation import reconcile_account, unresolved_orders
from fxrobot.market_data.sessions import calendar_span, is_fx_market_open
from fxrobot.market_data.validation import bar_problem
from fxrobot.models import (
    RiskProfile,
    Signal,
    StrategyAssignment,
    StrategyEvaluation,
    StrategyVersion,
    SystemState,
    TradingAccount,
)
from fxrobot.notifications.service import notify
from fxrobot.risk_engine.engine import evaluate as risk_evaluate
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.services import brokers as broker_service
from fxrobot.strategy_engine import Outcome, get_strategy
from fxrobot.strategy_engine.base import SignalIntent
from fxrobot.strategy_engine.view import StaticView
from fxrobot.trading_engine.context import build_risk_context

logger = logging.getLogger(__name__)

SYNC_INTERVAL_WALL = 15.0  # seconds between account syncs
SNAPSHOT_INTERVAL = timedelta(minutes=15)  # broker time between equity snapshots


@dataclass
class TickResult:
    account_id: uuid.UUID
    ok: bool
    detail: str
    signals: int = 0


@dataclass
class _RunnerState:
    last_sync_wall: float = 0.0
    last_snapshot: datetime | None = None
    account_info: AccountInfo | None = None
    notified: set[str] = field(default_factory=set)


def history_start(now: datetime, timeframe: Timeframe, bars: int) -> datetime:
    """Start time that comfortably covers `bars` closed bars, weekends included."""
    return now - calendar_span(timeframe.seconds, bars)


class AccountRunner:
    def __init__(
        self,
        manager: BrokerManager,
        execution: ExecutionEngine | None = None,
        *,
        live_locked: bool = True,
    ) -> None:
        self.manager = manager
        self.execution = execution or ExecutionEngine()
        self.live_locked = live_locked
        self._state: dict[uuid.UUID, _RunnerState] = {}

    def tick(self, db: Session, account_id: uuid.UUID) -> TickResult:
        account = db.get(TradingAccount, account_id)
        if account is None:
            return TickResult(account_id, True, "account removed")
        rs = self._state.setdefault(account_id, _RunnerState())
        try:
            adapter = self.manager.get(account.connection_id)
        except BrokerError as exc:
            return TickResult(account_id, False, f"broker unavailable: {exc}")
        try:
            adapter.advance()
            report = reconcile_account(db, account, adapter, self.execution)
            self._sync(db, account, adapter, rs)
            state = db.get(SystemState, 1)
            if state is None or state.kill_switch_engaged:
                return TickResult(account_id, True, "monitoring (trading stopped)")
            if report.orders_unresolved or unresolved_orders(db, account.id):
                return TickResult(account_id, True, "waiting for order reconciliation")
            signals = 0
            for assignment in db.scalars(
                select(StrategyAssignment).where(
                    StrategyAssignment.account_id == account.id,
                    StrategyAssignment.status == AssignmentStatus.ENABLED,
                )
            ):
                signals += self._run_assignment(db, account, assignment, adapter, state, rs)
            return TickResult(account_id, True, "ok", signals)
        except BrokerConnectionError as exc:
            db.rollback()
            self.manager.mark_failure(account.connection_id, str(exc))
            return TickResult(account_id, False, f"broker disconnected: {exc}")
        except BrokerError as exc:
            db.rollback()
            logger.warning("broker error on account %s: %s", account_id, exc)
            return TickResult(account_id, False, f"broker error: {exc}")

    # ── account sync ─────────────────────────────────────────────────────
    def _sync(
        self, db: Session, account: TradingAccount, adapter: BrokerAdapter, rs: _RunnerState
    ) -> None:
        wall = time.monotonic()
        now = adapter.now()
        due_snapshot = rs.last_snapshot is None or now - rs.last_snapshot >= SNAPSHOT_INTERVAL
        if wall - rs.last_sync_wall < SYNC_INTERVAL_WALL and not (
            adapter.is_simulated and due_snapshot
        ):
            return
        rs.last_sync_wall = wall
        rs.account_info = broker_service.sync_account(db, account, adapter, snapshot=due_snapshot)
        if due_snapshot:
            rs.last_snapshot = now
        bus.publish(
            "account",
            {
                "account_id": str(account.id),
                "balance": str(account.balance),
                "equity": str(account.equity),
            },
        )

    # ── strategies ───────────────────────────────────────────────────────
    def _run_assignment(
        self,
        db: Session,
        account: TradingAccount,
        assignment: StrategyAssignment,
        adapter: BrokerAdapter,
        state: SystemState,
        rs: _RunnerState,
    ) -> int:
        version = db.get(StrategyVersion, assignment.strategy_version_id)
        if version is None:
            return 0
        strategy = get_strategy(version.strategy.key)
        params = strategy.parse_params(version.parameters)
        timeframes = strategy.timeframes(params)
        entry_tf = timeframes[0]
        now = adapter.now()
        bar_open = entry_tf.floor(now) - entry_tf.delta
        if assignment.last_bar_evaluated is not None and assignment.last_bar_evaluated >= bar_open:
            return 0
        if not is_fx_market_open(bar_open) and not is_fx_market_open(now):
            return 0  # weekend: nothing to evaluate
        symbol = adapter.get_symbol(assignment.symbol)
        candles: dict[Timeframe, list[Candle]] = {}
        for tf, bars in strategy.required_bars(params).items():
            candles[tf] = adapter.get_candles(
                assignment.symbol, tf, history_start(now, tf, bars), now
            )
        bad = [bar_problem(c) for series in candles.values() for c in series]
        if any(bad):
            self._record_eval(
                db,
                assignment,
                bar_open,
                Outcome.INSUFFICIENT_DATA,
                "Malformed market data received — evaluation skipped.",
                [],
            )
            key = f"malformed:{account.id}:{bar_open.date()}"
            if key not in rs.notified:
                rs.notified.add(key)
                notify(
                    db,
                    "data.stale",
                    f"{assignment.symbol}: malformed candles from broker; "
                    "strategy evaluation skipped.",
                    account_id=account.id,
                )
            return 0
        ltf = candles.get(entry_tf, [])
        if not ltf or ltf[-1].time != bar_open:
            if now - (bar_open + entry_tf.delta) > entry_tf.delta * 0.5:
                self._record_eval(
                    db,
                    assignment,
                    bar_open,
                    Outcome.INSUFFICIENT_DATA,
                    "Latest bar missing from market data (gap or stale feed).",
                    [],
                )
            return 0
        evaluation = strategy.evaluate(StaticView(symbol, candles), params)
        self._record_eval(
            db,
            assignment,
            bar_open,
            evaluation.outcome,
            evaluation.summary,
            evaluation.checks_json(),
        )
        if evaluation.signal is None:
            return 0
        self._handle_signal(db, account, assignment, version, evaluation.signal, adapter, state, rs)
        return 1

    def _record_eval(
        self,
        db: Session,
        assignment: StrategyAssignment,
        bar_time: datetime,
        outcome: Outcome,
        summary: str,
        checks: list[dict[str, object]],
    ) -> None:
        db.add(
            StrategyEvaluation(
                assignment_id=assignment.id,
                bar_time=bar_time,
                outcome=outcome.value,
                summary=summary[:300],
                checks=checks,
                created_at=utcnow(),
            )
        )
        assignment.last_bar_evaluated = bar_time
        db.commit()
        bus.publish(
            "evaluation",
            {
                "assignment_id": str(assignment.id),
                "outcome": outcome.value,
                "summary": summary,
                "bar_time": bar_time.isoformat(),
            },
        )

    def _handle_signal(
        self,
        db: Session,
        account: TradingAccount,
        assignment: StrategyAssignment,
        version: StrategyVersion,
        intent: SignalIntent,
        adapter: BrokerAdapter,
        state: SystemState,
        rs: _RunnerState,
    ) -> None:
        cid = new_correlation_id()
        set_correlation_id(cid)
        signal = Signal(
            assignment_id=assignment.id,
            strategy_version_id=version.id,
            account_id=account.id,
            symbol=assignment.symbol,
            side=intent.side,
            timeframe=intent.timeframe,
            bar_time=intent.bar_time,
            entry_type=intent.entry_type,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            reasons=intent.reasons,
            status=SignalStatus.NEW,
            correlation_id=cid,
            created_at=utcnow(),
        )
        db.add(signal)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # duplicate signal for this bar: already handled
            logger.info("duplicate signal ignored for %s %s", assignment.symbol, intent.bar_time)
            return
        assignment.last_signal_at = utcnow()
        journal.record(
            db,
            EventType.SIGNAL_GENERATED,
            f"{intent.side.value} {assignment.symbol} signal "
            f"({version.strategy.name} v{version.version})",
            account_id=account.id,
            signal_id=signal.id,
            data={
                "reasons": intent.reasons,
                "entry": str(intent.entry_price),
                "stop_loss": str(intent.stop_loss),
                "take_profit": str(intent.take_profit),
            },
        )
        db.commit()
        notify(
            db,
            "signal.generated",
            f"{intent.side.value} {assignment.symbol}: " + "; ".join(intent.reasons[:2]),
            account_id=account.id,
            data={"signal_id": str(signal.id)},
        )

        profile = db.get(RiskProfile, account.risk_profile_id) if account.risk_profile_id else None
        if profile is None:
            self._reject(db, account, signal, "No risk profile assigned to this account", [])
            return
        symbol = adapter.get_symbol(assignment.symbol)
        info = rs.account_info
        with contextlib.suppress(BrokerError):
            info = adapter.get_account()
        ctx = build_risk_context(
            db,
            account=account,
            adapter=adapter,
            state=state,
            live_locked=self.live_locked,
            symbol=symbol,
            account_info=info,
            broker_connected=adapter.is_connected,
        )
        limits = RiskLimits.from_mapping(profile.as_dict())
        decision = risk_evaluate(intent, ctx, limits)
        signal.risk_checks = decision.checks_json()
        signal.decided_at = utcnow()
        if not decision.approved:
            self._reject(
                db, account, signal, decision.rejection_reason or "rejected", decision.checks_json()
            )
            failed = {c.rule for c in decision.checks if not c.passed}
            day = ctx.now.date().isoformat()
            for rule in failed & {"Daily loss limit", "Weekly loss limit", "Max drawdown"}:
                key = f"{account.id}:{rule}:{day}"
                if key not in rs.notified:
                    rs.notified.add(key)
                    notify(
                        db,
                        "risk.limit_reached",
                        f"{account.label}: {rule} reached — new trades blocked.",
                        account_id=account.id,
                    )
            if decision.halt_account:
                account.trading_enabled = False
                journal.record(
                    db,
                    EventType.ACCOUNT_HALTED,
                    "Maximum drawdown reached — trading disabled for this account. "
                    "Review before re-enabling.",
                    account_id=account.id,
                )
                db.commit()
            return
        signal.status = SignalStatus.APPROVED
        signal.volume, signal.risk_amount = decision.volume, decision.risk_amount
        journal.record(
            db,
            EventType.RISK_APPROVED,
            f"Risk approved {decision.volume} lots, "
            f"risking {decision.risk_amount} {account.currency}",
            account_id=account.id,
            signal_id=signal.id,
        )
        db.commit()
        quote = ctx.quote
        if quote is None:  # the data-fresh rule already guarantees a quote
            return
        self.execution.submit_entry(
            db,
            account=account,
            signal=signal,
            decision=decision,
            adapter=adapter,
            symbol=symbol,
            quote=quote,
        )

    def _reject(
        self,
        db: Session,
        account: TradingAccount,
        signal: Signal,
        reason: str,
        checks: list[dict[str, object]],
    ) -> None:
        signal.status = SignalStatus.REJECTED
        signal.rejection_reason = f"Trade rejected: {reason}"[:500]
        signal.risk_checks = checks
        signal.decided_at = utcnow()
        journal.record(
            db,
            EventType.RISK_REJECTED,
            signal.rejection_reason,
            account_id=account.id,
            signal_id=signal.id,
            data={"checks": checks},
        )
        db.commit()
        notify(
            db,
            "risk.rejected",
            f"{signal.side.value} {signal.symbol}: {reason}",
            account_id=account.id,
            data={"signal_id": str(signal.id)},
        )
