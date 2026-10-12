"""Build the risk engine's context from the database and the live broker.

The trading controls that apply to an account are the platform halt
(system_state) and its OWNER's own STOP switch, mode and LIVE authorisation
(user_trading_states) — never another user's.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import AccountInfo, Quote
from fxrobot.domain.contracts import ContractFamily, ContractOrder, ContractSpec, StakeQuote
from fxrobot.domain.market import Side, SymbolInfo
from fxrobot.domain.modes import (
    AUTHORISATION_MISMATCH,
    NOT_AUTHORISED,
    TradingControls,
    TradingMode,
)
from fxrobot.domain.trading import TradeStatus
from fxrobot.models import (
    AccountSnapshot,
    RiskProfile,
    Strategy,
    SystemState,
    Trade,
    TradingAccount,
    UserTradingState,
)
from fxrobot.risk_engine.engine import OpenExposure, RiskContext, resolved_stake
from fxrobot.risk_engine.limits import RiskLimits


def day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(moment: datetime) -> datetime:
    return day_start(moment) - timedelta(days=moment.weekday())


def load_controls(db: Session, account: TradingAccount, *, live_locked: bool) -> TradingControls:
    """Read the switches for `account` now. Missing rows mean the safe default (stopped)."""
    platform = db.get(SystemState, 1)
    owner = db.get(UserTradingState, account.user_id)
    problem = live_authorization_problem(db, account, owner)
    return TradingControls(
        platform_halted=platform is None or platform.kill_switch_engaged,
        kill_switch_engaged=owner is None or owner.kill_switch_engaged,
        mode=owner.trading_mode if owner is not None else TradingMode.DEMO,
        live_authorized=problem is None,
        live_trading_locked=live_locked,
        live_authorization_problem=problem,
    )


def live_authorization_problem(
    db: Session, account: TradingAccount, owner: UserTradingState | None
) -> str | None:
    """Why the owner's real-money authorisation does not cover `account`; None = it does.

    The authorisation (MFA + password + typed phrase in Laravel) is bound to ONE
    account and the risk profile it had: it covers the account only while that
    profile is still assigned and has not been edited since the authorisation.
    """
    if owner is None or owner.live_authorized_at is None:
        return NOT_AUTHORISED
    if owner.live_authorized_account_id != account.id:
        return f"{AUTHORISATION_MISMATCH} (it was given for another account)"
    if (
        account.risk_profile_id is None
        or account.risk_profile_id != owner.live_authorized_profile_id
    ):
        return f"{AUTHORISATION_MISMATCH} (the account's risk profile was changed)"
    profile = db.get(RiskProfile, account.risk_profile_id)
    if profile is None or profile.updated_at > owner.live_authorized_at:
        return f"{AUTHORISATION_MISMATCH} (the risk limits were edited since)"
    return None


def strategy_stop_reason(strategy: Strategy | None) -> str | None:
    """Why new entries from `strategy` are blocked by an administrator's emergency
    stop (on the strategy itself, or on the built-in it was copied from). Open
    positions are never closed by it."""
    for row in (strategy, strategy.copied_from if strategy is not None else None):
        if row is not None and row.entries_disabled_at is not None:
            reason = row.entries_disabled_reason or "no reason given"
            which = "" if row is strategy else f" (copied from {row.name})"
            return (
                f"new entries from {row.name}{which} are stopped by an administrator: {reason}"
            )[:300]
    return None


def build_risk_context(
    db: Session,
    *,
    account: TradingAccount,
    adapter: BrokerAdapter,
    controls: TradingControls,
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
    consecutive_today = 0
    for trade in recent:
        if trade.exit_time is None or trade.exit_time < d0:
            break
        if trade.net_pnl is not None and trade.net_pnl < 0:
            consecutive_today += 1
        else:
            break
    last_loss = recent[0].exit_time if recent and consecutive else None
    # Closed without a confirmed P/L (broker history lagging): reconciliation keeps
    # retrying; until then the loss limits above cannot see it, so it blocks entries.
    unsettled = int(
        db.scalar(
            select(func.count()).where(
                Trade.account_id == account.id,
                Trade.status == TradeStatus.CLOSED,
                Trade.net_pnl.is_(None),
            )
        )
        or 0
    )

    balance = account_info.balance if account_info else account.balance
    equity = account_info.equity if account_info else account.equity
    peak = db.scalar(
        select(func.max(AccountSnapshot.equity)).where(AccountSnapshot.account_id == account.id)
    )
    peak_equity = max(filter(None, [peak, equity]), default=None)
    return RiskContext(
        now=now,
        mode=controls.mode,
        kill_switch_engaged=controls.kill_switch_engaged,
        platform_halted=controls.platform_halted,
        live_trading_locked=controls.live_trading_locked,
        live_authorized=controls.live_authorized,
        live_authorization_problem=controls.live_authorization_problem,
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
        consecutive_losses_today=consecutive_today,
        unsettled_trades=unsettled,
    )


def attach_contract(
    ctx: RiskContext,
    adapter: BrokerAdapter,
    spec: ContractSpec,
    side: Side,
    limits: RiskLimits,
) -> None:
    """Tell the risk engine what will be bought and what the broker says about it.

    Reads the broker's offer for the symbol (Deriv: `contracts_for`, cached) and,
    for contracts, prices the exact contract (Deriv: a `proposal`) to learn the
    stake limits. Nothing is bought. Failures become explained rejections.
    """
    ctx.contract = spec
    offered = adapter.capabilities.contract_families
    family = spec.contract_family
    if family.value not in offered:
        ctx.contract_problem = (
            f"{adapter.connector_id.capitalize()} accounts trade contracts: choose "
            "Rise/Fall or Multiplier."
            if family is ContractFamily.SPOT
            else f"{spec.label()} is not offered by {adapter.connector_id.capitalize()}."
        )
        return
    if not family.is_contract:
        return
    try:
        problem = adapter.contract_capabilities(ctx.symbol.name).check(spec)
    except BrokerError as exc:
        ctx.contract_problem = f"could not read the broker's contract offer: {exc}"
        return
    if problem:
        ctx.contract_problem = problem
        return
    order = ContractOrder.build(spec, side, resolved_stake(ctx, limits))
    try:
        ctx.stake_quote = adapter.quote_contract(ctx.symbol.name, order)
    except BrokerError as exc:
        ctx.stake_quote = StakeQuote(None, None, detail=str(exc))
