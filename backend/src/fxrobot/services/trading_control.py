"""Global trading controls: the kill switch and the operating mode.

Rules enforced here (and tested in tests/test_trading_control.py):

* The kill switch is ENGAGED on a fresh install.
* Engaging the kill switch is always allowed for an owner and is idempotent.
  It blocks new orders and automated execution; it never closes positions.
* The operating mode can only change while the kill switch is engaged.
* LIVE mode additionally requires: the LIVE_TRADING_ENABLED hard lock to be
  off, the owner's password, and a typed confirmation phrase.
* Every attempt — allowed or refused — is audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.config import Settings
from fxrobot.core.errors import ConflictError, PermissionDeniedError
from fxrobot.domain.modes import TradingMode
from fxrobot.models import AuditOutcome, SystemState, User
from fxrobot.services import audit
from fxrobot.services.auth import reverify_password, utcnow
from fxrobot.services.context import RequestMeta

LIVE_CONFIRMATION_PHRASE = "ENABLE LIVE TRADING"


class EngineState(StrEnum):
    # Only OFFLINE exists until the trading engine lands (Phase 7);
    # RUNNING / DEGRADED will be reported by the engine's heartbeat.
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class TradingStatus:
    state: SystemState
    live_trading_locked: bool
    engine_state: EngineState
    engine_detail: str

    @property
    def new_orders_permitted(self) -> bool:
        """The single answer to 'may anything open a new trade right now?'."""
        if self.state.kill_switch_engaged:
            return False
        if self.state.trading_mode is TradingMode.LIVE and self.live_trading_locked:
            return False
        return self.state.trading_mode is not TradingMode.BACKTEST


def _load_state(db: Session, *, for_update: bool = False) -> SystemState:
    stmt = select(SystemState).where(SystemState.id == 1)
    if for_update:
        stmt = stmt.with_for_update()
    state = db.scalar(stmt)
    if state is None:  # the migration seeds this row; recreate defensively (engaged)
        state = SystemState(id=1, trading_mode=TradingMode.DEMO, kill_switch_engaged=True)
        db.add(state)
        db.flush()
    return state


def get_status(db: Session, settings: Settings) -> TradingStatus:
    return TradingStatus(
        state=_load_state(db),
        live_trading_locked=not settings.live_trading_enabled,
        engine_state=EngineState.OFFLINE,
        engine_detail="The automated trading engine is not built yet (Phase 7). "
        "No strategy can place orders.",
    )


def engage_kill_switch(db: Session, *, actor: User, reason: str, meta: RequestMeta) -> SystemState:
    state = _load_state(db, for_update=True)
    already = state.kill_switch_engaged
    if not already:
        state.kill_switch_engaged = True
        state.kill_switch_reason = reason
        state.kill_switch_changed_at = utcnow()
        state.kill_switch_changed_by = actor.id
    audit.record(
        db,
        action="trading.kill_switch.engaged",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="system",
        details={"reason": reason, "already_engaged": already},
    )
    db.commit()
    return state


def release_kill_switch(db: Session, *, actor: User, meta: RequestMeta) -> SystemState:
    state = _load_state(db, for_update=True)
    if not state.kill_switch_engaged:
        db.rollback()
        return state
    state.kill_switch_engaged = False
    state.kill_switch_reason = None
    state.kill_switch_changed_at = utcnow()
    state.kill_switch_changed_by = actor.id
    audit.record(
        db,
        action="trading.kill_switch.released",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="system",
        details={"mode": state.trading_mode.value},
    )
    db.commit()
    return state


def set_mode(
    db: Session,
    *,
    actor: User,
    mode: TradingMode,
    settings: Settings,
    meta: RequestMeta,
    password: str | None = None,
    confirmation_phrase: str | None = None,
) -> SystemState:
    state = _load_state(db, for_update=True)
    previous = state.trading_mode

    def deny(reason: str, exc: type[PermissionDeniedError | ConflictError]) -> None:
        audit.record(
            db,
            action="trading.mode.change_denied",
            outcome=AuditOutcome.DENIED,
            actor=actor,
            meta=meta,
            target_type="system",
            details={"from": previous.value, "to": mode.value, "reason": reason},
        )
        db.commit()
        raise exc(reason)

    if mode is previous:
        db.rollback()
        return state
    if not state.kill_switch_engaged:
        deny("Stop all trading before changing the operating mode.", ConflictError)
    if mode is TradingMode.LIVE:
        if not settings.live_trading_enabled:
            deny(
                "LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).",
                PermissionDeniedError,
            )
        if not reverify_password(actor, password):
            deny("Password confirmation failed.", PermissionDeniedError)
        if (confirmation_phrase or "").strip() != LIVE_CONFIRMATION_PHRASE:
            deny(f"Type '{LIVE_CONFIRMATION_PHRASE}' to confirm.", PermissionDeniedError)

    state.trading_mode = mode
    state.mode_changed_at = utcnow()
    state.mode_changed_by = actor.id
    audit.record(
        db,
        action="trading.mode.live_enabled" if mode is TradingMode.LIVE else "trading.mode.changed",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="system",
        details={"from": previous.value, "to": mode.value},
    )
    db.commit()
    return state
