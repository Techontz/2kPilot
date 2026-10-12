"""Rule evaluation and position sizing.

`evaluate` is a pure function of (signal, context, limits) so live trading
and backtesting run the exact same checks. Callers assemble `RiskContext`
from their own state (database + broker live; simulation state in backtests).

The switches are passed in, never looked up: the account OWNER's STOP switch,
mode and LIVE authorisation, the platform halt, and the server LIVE lock.

Contracts (Rise/Fall, Multipliers) are sized by a fixed stake instead of lots:
the stake is the most a contract can lose (a Rise/Fall settles at expiry; a
Multiplier is stopped out by the broker before the loss exceeds the stake), so
a bounded stake satisfies the stop-loss requirement. Their extra checks are the
broker's stake limits (read from the broker's price for the contract — never
hard-coded; missing limits fail closed), the profile's stake cap and the money
limits. Lot-based checks (stop distance, reward/risk, lot exposure, margin) do
not apply to contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from fxrobot.domain.contracts import (
    ContractFamily,
    ContractOrder,
    ContractSpec,
    StakeQuote,
    multiplier_limit_amounts,
)
from fxrobot.domain.market import Quote, Side, SymbolInfo
from fxrobot.domain.modes import AccountEnvironment, TradingMode, environment_permitted
from fxrobot.market_data.conversion import QuoteLookup, conversion_rate, point_value
from fxrobot.market_data.sessions import is_fx_market_open, session_at
from fxrobot.risk_engine.limits import RiskLimits, parse_hhmm
from fxrobot.strategy_engine.base import SignalIntent


@dataclass(frozen=True)
class OpenExposure:
    symbol: str
    side: Side
    volume: Decimal
    risk_amount: Decimal | None  # None = unknown (treated conservatively)


@dataclass
class RiskContext:
    now: datetime
    mode: TradingMode  # the account owner's operating mode
    kill_switch_engaged: bool  # the account owner's own STOP switch
    platform_halted: bool  # admin emergency halt for every user
    live_trading_locked: bool  # server hard lock (LIVE_TRADING_ENABLED=false)
    live_authorized: bool  # the owner's LIVE authorisation covers this account and its limits
    account_environment: AccountEnvironment
    account_trading_enabled: bool
    broker_connected: bool
    account_currency: str
    balance: Decimal | None
    equity: Decimal | None
    free_margin: Decimal | None
    leverage: int | None
    symbol: SymbolInfo
    quote: Quote | None
    quote_lookup: QuoteLookup
    open_positions: list[OpenExposure] = field(default_factory=list)
    realized_pnl_today: Decimal = Decimal(0)
    realized_pnl_week: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    start_of_day_balance: Decimal | None = None
    start_of_week_balance: Decimal | None = None
    peak_equity: Decimal | None = None
    trades_today: int = 0
    consecutive_losses: int = 0
    last_loss_at: datetime | None = None
    check_market_hours: bool = True
    # A manual ticket from the Trade page: same rules, but there is no strategy
    # bar whose age must be checked, and the person chooses the volume.
    manual: bool = False
    # ── contracts ──
    contract: ContractSpec = field(default_factory=ContractSpec)
    # Why the broker cannot trade this contract on this symbol (capabilities), if so.
    contract_problem: str | None = None
    # The broker's price for the contract (stake limits); None = not available.
    stake_quote: StakeQuote | None = None
    # Losses in a row among trades closed TODAY (UTC); resets at midnight.
    consecutive_losses_today: int = 0
    # Why the LIVE authorisation does not cover this account (shown when it does not).
    live_authorization_problem: str | None = None
    # Closed trades whose P/L the broker has not confirmed yet: the loss limits
    # cannot be trusted until they are settled, so they block new entries.
    unsettled_trades: int = 0
    # Why the strategy behind this signal may not open trades (an administrator's
    # emergency stop for that strategy). None = it may; manual tickets have none.
    strategy_disabled: str | None = None


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "passed": self.passed, "detail": self.detail}


@dataclass
class RiskDecision:
    approved: bool
    checks: list[RuleResult]
    volume: Decimal | None = None
    risk_amount: Decimal | None = None
    max_slippage_points: int | None = None
    halt_account: bool = False  # a hard limit (drawdown) was breached: stop this account
    contract: ContractOrder | None = None  # set for approved contract trades (volume = 1)
    payout: Decimal | None = None  # Rise/Fall: what the broker quoted to pay if it wins

    @property
    def rejection_reason(self) -> str | None:
        failed = next((c for c in self.checks if not c.passed), None)
        return None if failed is None else f"{failed.rule}: {failed.detail}"

    def checks_json(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.checks]


Rule = Callable[[SignalIntent, RiskContext, RiskLimits], RuleResult]


CENT = Decimal("0.01")


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def _pips(distance: Decimal, symbol: SymbolInfo) -> Decimal:
    return (abs(distance) / symbol.pip_size).quantize(Decimal("0.1"))


def _money(value: Decimal, currency: str) -> str:
    return f"{value.quantize(Decimal('0.01'))} {currency}"


def resolved_stake(c: RiskContext, lim: RiskLimits) -> Decimal:
    """The stake of the next contract: the contract spec's own stake, else the profile's."""
    return c.contract.stake if c.contract.stake is not None else lim.stake_amount


def _is_contract(c: RiskContext) -> bool:
    return c.contract.contract_family.is_contract


def _is_synthetic(c: RiskContext) -> bool:
    """Deriv's synthetic indices (Volatility, Boom/Crash, …): open 24/7, no FX sessions."""
    return c.symbol.category == "synthetic"


# ── individual rules (each pure, each explainable) ───────────────────────


def rule_kill_switch(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    if c.platform_halted:
        return RuleResult(
            "Kill switch", False, "trading is halted platform-wide by an administrator"
        )
    return RuleResult(
        "Kill switch",
        not c.kill_switch_engaged,
        "STOP ALL TRADING is engaged" if c.kill_switch_engaged else "released",
    )


def rule_strategy_enabled(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    if c.strategy_disabled:
        return RuleResult("Strategy enabled", False, c.strategy_disabled)
    return RuleResult("Strategy enabled", True, "no emergency stop on this strategy")


def rule_min_balance(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    name = "Minimum balance"
    if lim.min_account_balance is None:
        return RuleResult(name, True, "no minimum")
    floor = _money(lim.min_account_balance, c.account_currency)
    if c.balance is None:
        return RuleResult(name, False, f"balance unknown (minimum {floor})")
    if c.balance < lim.min_account_balance:
        return RuleResult(
            name,
            False,
            f"balance {_money(c.balance, c.account_currency)} is below the minimum {floor}",
        )
    return RuleResult(name, True, f"balance {_money(c.balance, c.account_currency)} ≥ {floor}")


def rule_mode(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    ok = environment_permitted(c.mode, c.account_environment)
    if ok and c.account_environment is AccountEnvironment.LIVE and c.live_trading_locked:
        return RuleResult("Operating mode", False, "LIVE account but the LIVE hard lock is on")
    if ok and c.account_environment is AccountEnvironment.LIVE and not c.live_authorized:
        return RuleResult(
            "Operating mode",
            False,
            c.live_authorization_problem
            or "LIVE trading has not been authorised by the account owner",
        )
    return RuleResult(
        "Operating mode",
        ok,
        f"{c.account_environment.value} account allowed in {c.mode.value} mode"
        if ok
        else f"{c.account_environment.value} account not allowed in {c.mode.value} mode",
    )


def rule_account_enabled(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    return RuleResult(
        "Account trading enabled",
        c.account_trading_enabled,
        "enabled" if c.account_trading_enabled else "trading is disabled for this account",
    )


def rule_broker(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    return RuleResult(
        "Broker connected",
        c.broker_connected,
        "connected" if c.broker_connected else "broker disconnected",
    )


def rule_contract(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    if c.contract_problem:
        return RuleResult("Contract supported", False, c.contract_problem)
    return RuleResult("Contract supported", True, c.contract.label())


def rule_stop_loss(s: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    family = c.contract.contract_family
    if family is ContractFamily.RISE_FALL:
        return RuleResult(
            "Stop loss required", True, "bounded: a Rise/Fall can lose at most its stake"
        )
    if family is ContractFamily.MULTIPLIER:
        return RuleResult(
            "Stop loss required",
            True,
            "bounded: the broker stops a Multiplier out before it loses more than its stake",
        )
    if s.stop_loss is None or s.stop_loss <= 0:
        return RuleResult("Stop loss required", False, "signal has no stop loss")
    if (s.entry_price - s.stop_loss) * s.side.sign <= 0:
        return RuleResult("Stop loss required", False, "stop loss is on the wrong side of entry")
    return RuleResult("Stop loss required", True, f"stop at {s.stop_loss}")


def rule_data_fresh(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if c.quote is None:
        return RuleResult("Market data fresh", False, "no current price")
    age = (c.now - c.quote.time).total_seconds()
    if age > lim.max_data_age_seconds:
        return RuleResult(
            "Market data fresh",
            False,
            f"price is {int(age)}s old (max {lim.max_data_age_seconds}s)",
        )
    if c.manual:
        return RuleResult("Market data fresh", True, f"price {int(age)}s old")
    bar_close = s.bar_time + s.timeframe.delta
    signal_age = (c.now - bar_close).total_seconds()
    max_signal_age = s.timeframe.seconds * 0.5
    if signal_age < 0 or signal_age > max_signal_age:
        return RuleResult(
            "Market data fresh",
            False,
            f"signal bar closed {int(signal_age)}s ago (max {int(max_signal_age)}s)",
        )
    return RuleResult("Market data fresh", True, f"price {int(age)}s old")


def rule_market_open(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if not c.check_market_hours:
        return RuleResult("Market open", True, "not checked (simulation)")
    if not c.symbol.trade_allowed:
        return RuleResult("Market open", False, f"trading on {c.symbol.name} is suspended (broker)")
    if c.symbol.market_open is not None:  # the broker told us
        if not c.symbol.market_open:
            return RuleResult("Market open", False, f"{c.symbol.name} market is closed (broker)")
        return RuleResult("Market open", True, "open (broker)")
    if not is_fx_market_open(c.now):
        return RuleResult("Market open", False, "FX market is closed (weekend)")
    return RuleResult("Market open", True, "open")


def rule_trading_hours(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if lim.trading_hours_start is None or lim.trading_hours_end is None:
        return RuleResult("Trading hours", True, "any time")
    start, end = parse_hhmm(lim.trading_hours_start), parse_hhmm(lim.trading_hours_end)
    if start is None or end is None:
        return RuleResult("Trading hours", False, "trading hours are misconfigured")
    now = c.now.hour * 60 + c.now.minute
    inside = start <= now < end if start < end else (now >= start or now < end)
    window = f"{lim.trading_hours_start}–{lim.trading_hours_end} UTC"
    if not inside:
        return RuleResult("Trading hours", False, f"{c.now:%H:%M} UTC is outside {window}")
    return RuleResult("Trading hours", True, f"inside {window}")


def rule_session(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    session = session_at(c.now).value
    if _is_synthetic(c):
        return RuleResult(
            "Trading session",
            True,
            f"{session}: not applicable, synthetic indices trade around the clock",
        )
    if lim.allowed_sessions and session not in lim.allowed_sessions:
        return RuleResult(
            "Trading session",
            False,
            f"{session} session not allowed ({', '.join(lim.allowed_sessions)})",
        )
    return RuleResult("Trading session", True, session)


def rule_spread(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if c.quote is None:
        return RuleResult("Spread", False, "no current price")
    spread = _pips(c.quote.spread, c.symbol)
    if _is_synthetic(c) and _is_contract(c):
        # A pip limit is a forex measure; on R_75 (~40,000) a normal 8-point spread is
        # "80,000 pips". Deriv prices each contract (payout or commission) up front.
        return RuleResult(
            "Spread", True, f"{spread} pips: not applicable, Deriv prices the contract"
        )
    if lim.max_spread_pips is not None and spread > lim.max_spread_pips:
        return RuleResult("Spread", False, f"{spread} pips > max {lim.max_spread_pips}")
    return RuleResult("Spread", True, f"{spread} pips")


def rule_stop_distance(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if _is_contract(c):
        return RuleResult("Stop distance", True, "not applicable: contracts are sized by stake")
    pips = _pips(s.risk_distance, c.symbol)
    if lim.min_stop_pips is not None and pips < lim.min_stop_pips:
        return RuleResult("Stop distance", False, f"{pips} pips < min {lim.min_stop_pips}")
    if lim.max_stop_pips is not None and pips > lim.max_stop_pips:
        return RuleResult("Stop distance", False, f"{pips} pips > max {lim.max_stop_pips}")
    return RuleResult("Stop distance", True, f"{pips} pips")


def rule_reward_risk(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if _is_contract(c):
        return RuleResult("Reward/risk", True, "not applicable: the contract fixes the payout")
    rr = s.reward_risk
    if lim.min_reward_risk is None:
        return RuleResult("Reward/risk", True, "no minimum" if rr is None else f"1:{rr:.2f}")
    if rr is None:
        return RuleResult("Reward/risk", False, "signal has no take profit")
    if rr < lim.min_reward_risk:
        return RuleResult("Reward/risk", False, f"1:{rr:.2f} < min 1:{lim.min_reward_risk}")
    return RuleResult("Reward/risk", True, f"1:{rr:.2f}")


def _loss_rule(name: str, pnl: Decimal, base: Decimal | None, limit: Decimal | None) -> RuleResult:
    if limit is None:
        return RuleResult(name, True, "no limit")
    if base is None or base <= 0:
        return RuleResult(name, False, "reference balance unknown")
    loss_pct = max(Decimal(0), -pnl) / base * 100
    if loss_pct >= limit:
        return RuleResult(name, False, f"loss {_pct(loss_pct)} reached limit {_pct(limit)}")
    return RuleResult(name, True, f"loss {_pct(loss_pct)} of {_pct(limit)}")


def rule_daily_loss(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    return _loss_rule(
        "Daily loss limit",
        c.realized_pnl_today + c.unrealized_pnl,
        c.start_of_day_balance,
        lim.max_daily_loss_pct,
    )


def rule_weekly_loss(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    return _loss_rule(
        "Weekly loss limit",
        c.realized_pnl_week + c.unrealized_pnl,
        c.start_of_week_balance,
        lim.max_weekly_loss_pct,
    )


def rule_drawdown(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if lim.max_drawdown_pct is None:
        return RuleResult("Max drawdown", True, "no limit")
    if c.equity is None or c.peak_equity is None or c.peak_equity <= 0:
        return RuleResult("Max drawdown", False, "equity history unknown")
    dd = max(Decimal(0), (c.peak_equity - c.equity) / c.peak_equity * 100)
    if dd >= lim.max_drawdown_pct:
        return RuleResult(
            "Max drawdown", False, f"drawdown {_pct(dd)} reached limit {_pct(lim.max_drawdown_pct)}"
        )
    return RuleResult("Max drawdown", True, f"drawdown {_pct(dd)} of {_pct(lim.max_drawdown_pct)}")


def rule_settlement(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    """A closed trade without a confirmed P/L could hide a loss the limits must count."""
    if c.unsettled_trades:
        return RuleResult(
            "Settled P/L",
            False,
            f"{c.unsettled_trades} closed trade(s) have no confirmed P/L yet — new trades are "
            "blocked until the broker's history settles them",
        )
    return RuleResult("Settled P/L", True, "every closed trade has a confirmed P/L")


def rule_cooldown(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if lim.cooldown_after_losses is None or lim.cooldown_minutes is None:
        return RuleResult("Loss cooldown", True, "no cooldown")
    if c.consecutive_losses >= lim.cooldown_after_losses and c.last_loss_at is not None:
        until = c.last_loss_at + timedelta(minutes=lim.cooldown_minutes)
        if c.now < until:
            mins = int((until - c.now).total_seconds() // 60) + 1
            return RuleResult(
                "Loss cooldown",
                False,
                f"{c.consecutive_losses} losses in a row — paused for {mins} more min",
            )
    return RuleResult("Loss cooldown", True, f"{c.consecutive_losses} consecutive losses")


def rule_daily_loss_amount(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    name = "Daily loss amount"
    if lim.max_daily_loss_amount is None:
        return RuleResult(name, True, "no limit")
    limit = lim.max_daily_loss_amount
    lost = max(Decimal(0), -(c.realized_pnl_today + c.unrealized_pnl))
    if lost >= limit:
        return RuleResult(
            name,
            False,
            f"lost {_money(lost, c.account_currency)} today, limit "
            f"{_money(limit, c.account_currency)} — no new trades until 00:00 UTC",
        )
    if _is_contract(c):
        # Worst case: every open contract loses its whole stake, then this one too.
        if any(p.risk_amount is None for p in c.open_positions):
            return RuleResult(name, False, "risk of an open position is unknown")
        open_risk = sum((p.risk_amount or Decimal(0) for p in c.open_positions), Decimal(0))
        stake = resolved_stake(c, lim)
        worst = max(Decimal(0), open_risk - c.realized_pnl_today) + stake
        if worst > limit:
            held = (
                f" plus {_money(open_risk, c.account_currency)} in open contracts"
                if open_risk
                else ""
            )
            return RuleResult(
                name,
                False,
                f"losing this {_money(stake, c.account_currency)} stake{held} would take "
                f"today's loss to {_money(worst, c.account_currency)}, above the limit "
                f"{_money(limit, c.account_currency)}",
            )
    return RuleResult(
        name,
        True,
        f"lost {_money(lost, c.account_currency)} of {_money(limit, c.account_currency)} today",
    )


def rule_losing_streak(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    name = "Losing streak"
    if lim.max_consecutive_losses is None:
        return RuleResult(name, True, "no limit")
    if c.consecutive_losses_today >= lim.max_consecutive_losses:
        return RuleResult(
            name,
            False,
            f"{c.consecutive_losses_today} losses in a row today (max "
            f"{lim.max_consecutive_losses}) — trading halted until 00:00 UTC",
        )
    return RuleResult(
        name,
        True,
        f"{c.consecutive_losses_today} losses in a row today (max {lim.max_consecutive_losses})",
    )


def rule_profit_target(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    name = "Daily profit target"
    if lim.daily_profit_target_amount is None:
        return RuleResult(name, True, "no target")
    target = lim.daily_profit_target_amount
    if c.realized_pnl_today >= target:
        return RuleResult(
            name,
            False,
            f"target reached: +{_money(c.realized_pnl_today, c.account_currency)} of "
            f"{_money(target, c.account_currency)} — stopping for today",
        )
    return RuleResult(
        name,
        True,
        f"{_money(c.realized_pnl_today, c.account_currency)} of "
        f"{_money(target, c.account_currency)} today",
    )


def rule_trades_per_day(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    if lim.max_trades_per_day is not None and c.trades_today >= lim.max_trades_per_day:
        return RuleResult(
            "Trades per day", False, f"{c.trades_today} of {lim.max_trades_per_day} used"
        )
    return RuleResult("Trades per day", True, f"{c.trades_today} today")


def rule_open_positions(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    total = len(c.open_positions)
    same = sum(1 for p in c.open_positions if p.symbol == c.symbol.name)
    if lim.max_open_positions is not None and total >= lim.max_open_positions:
        return RuleResult("Open positions", False, f"{total} open (max {lim.max_open_positions})")
    if lim.max_positions_per_symbol is not None and same >= lim.max_positions_per_symbol:
        return RuleResult(
            "Open positions",
            False,
            f"{same} open on {c.symbol.name} (max {lim.max_positions_per_symbol})",
        )
    return RuleResult("Open positions", True, f"{total} open, {same} on {c.symbol.name}")


RULES: tuple[Rule, ...] = (
    rule_kill_switch,
    rule_strategy_enabled,
    rule_mode,
    rule_account_enabled,
    rule_broker,
    rule_contract,
    rule_stop_loss,
    rule_data_fresh,
    rule_market_open,
    rule_session,
    rule_trading_hours,
    rule_spread,
    rule_stop_distance,
    rule_reward_risk,
    rule_daily_loss,
    rule_weekly_loss,
    rule_drawdown,
    rule_min_balance,
    rule_settlement,
    rule_cooldown,
    rule_losing_streak,
    rule_daily_loss_amount,
    rule_profit_target,
    rule_trades_per_day,
    rule_open_positions,
)


# ── sizing ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Sizing:
    volume: Decimal | None
    risk_amount: Decimal | None
    detail: str


def size_position(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> Sizing:
    """Volume so that hitting the stop loses at most risk_per_trade_pct of equity.

    Rounded DOWN to the broker's volume step; if that falls below the minimum
    volume the trade is rejected (never rounded up into more risk).
    """
    if c.equity is None or c.equity <= 0:
        return Sizing(None, None, "equity unknown")
    pv = point_value(c.symbol, c.account_currency, c.quote_lookup)
    if pv is None or pv <= 0:
        return Sizing(
            None, None, f"cannot convert {c.symbol.quote_currency} to {c.account_currency}"
        )
    stop_points = s.risk_distance / c.symbol.point
    loss_per_lot = stop_points * pv
    if loss_per_lot <= 0:
        return Sizing(None, None, "zero stop distance")
    budget = c.equity * lim.risk_per_trade_pct / 100
    raw = budget / loss_per_lot
    step = c.symbol.volume_step
    volume = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
    caps = [c.symbol.volume_max]
    if lim.max_position_lots is not None:
        caps.append(lim.max_position_lots)
    cap = min(caps)
    if volume > cap:
        volume = (cap / step).to_integral_value(rounding=ROUND_DOWN) * step
    if volume < c.symbol.volume_min:
        return Sizing(
            None,
            None,
            f"risk budget {budget:.2f} {c.account_currency} buys {raw:.4f} lots, "
            f"below the minimum {c.symbol.volume_min}",
        )
    risk = (volume * loss_per_lot).quantize(Decimal("0.01"))
    return Sizing(
        volume.normalize(),
        risk,
        f"{volume.normalize()} lots risks {risk} {c.account_currency} "
        f"({lim.risk_per_trade_pct}% budget {budget:.2f})",
    )


def rule_symbol_exposure(volume: Decimal, c: RiskContext, lim: RiskLimits) -> RuleResult:
    lots = (
        sum((p.volume for p in c.open_positions if p.symbol == c.symbol.name), Decimal(0)) + volume
    )
    if lim.max_symbol_exposure_lots is not None and lots > lim.max_symbol_exposure_lots:
        return RuleResult(
            "Symbol exposure",
            False,
            f"{lots} lots on {c.symbol.name} > max {lim.max_symbol_exposure_lots}",
        )
    return RuleResult("Symbol exposure", True, f"{lots} lots on {c.symbol.name} after this trade")


def rule_exposure(volume: Decimal, risk: Decimal, c: RiskContext, lim: RiskLimits) -> RuleResult:
    lots = sum((p.volume for p in c.open_positions), Decimal(0)) + volume
    if lim.max_total_exposure_lots is not None and lots > lim.max_total_exposure_lots:
        return RuleResult(
            "Total exposure", False, f"{lots} lots > max {lim.max_total_exposure_lots}"
        )
    if lim.max_total_risk_pct is not None:
        if any(p.risk_amount is None for p in c.open_positions):
            return RuleResult("Total exposure", False, "risk of an open position is unknown")
        if c.equity is None or c.equity <= 0:
            return RuleResult("Total exposure", False, "equity unknown")
        open_risk = sum((p.risk_amount or Decimal(0) for p in c.open_positions), Decimal(0)) + risk
        pct = open_risk / c.equity * 100
        if pct > lim.max_total_risk_pct:
            return RuleResult(
                "Total exposure",
                False,
                f"open risk {_pct(pct)} > max {_pct(lim.max_total_risk_pct)}",
            )
    return RuleResult("Total exposure", True, f"{lots} lots after this trade")


def rule_margin(volume: Decimal, c: RiskContext) -> RuleResult:
    if c.leverage is None or c.free_margin is None:
        return RuleResult("Margin", True, "broker enforces margin")
    rate = conversion_rate(c.symbol.base_currency, c.account_currency, c.quote_lookup)
    if rate is None and c.symbol.base_currency in (c.symbol.name, c.symbol.canonical_name):
        # An index (e.g. R_10) is its own "base currency": one unit is worth its price
        # in the quote currency.
        to_account = conversion_rate(c.symbol.quote_currency, c.account_currency, c.quote_lookup)
        if c.quote is not None and c.quote.mid > 0 and to_account is not None:
            rate = c.quote.mid * to_account
    if rate is None:
        return RuleResult("Margin", False, f"cannot value {c.symbol.base_currency} exposure")
    required = volume * c.symbol.contract_size * rate / Decimal(c.leverage)
    if required > c.free_margin:
        return RuleResult("Margin", False, f"needs {required:.2f}, free {c.free_margin:.2f}")
    return RuleResult("Margin", True, f"needs {required:.2f} of {c.free_margin:.2f} free")


def rule_stake(c: RiskContext, lim: RiskLimits) -> RuleResult:
    """The stake must fit the profile cap, the balance and the BROKER's stake limits.

    The broker's limits come from its price for this exact contract (Deriv:
    `proposal.validation_params.stake`). If the broker did not report them we
    cannot know the stake is acceptable, so the trade is refused (fail closed).
    """
    name = "Stake"
    ccy = c.account_currency
    stake = resolved_stake(c, lim)
    if stake <= 0:
        return RuleResult(name, False, "stake must be positive")
    if lim.max_stake_amount is not None and stake > lim.max_stake_amount:
        return RuleResult(
            name,
            False,
            f"{_money(stake, ccy)} is above the profile's maximum stake "
            f"{_money(lim.max_stake_amount, ccy)}",
        )
    spec = c.contract
    if (
        spec.contract_family is ContractFamily.MULTIPLIER
        and spec.stop_loss_amount is not None
        and spec.stop_loss_amount > stake
    ):
        return RuleResult(
            name,
            False,
            f"the stop-loss amount {_money(spec.stop_loss_amount, ccy)} is larger than the stake "
            f"{_money(stake, ccy)}",
        )
    if c.balance is None or stake > c.balance:
        return RuleResult(name, False, f"{_money(stake, ccy)} is more than the balance")
    # The stake is the most a contract can lose: it must fit the per-trade budget
    # like any other trade. Refused, never shrunk to fit.
    budget = c.balance * lim.risk_per_trade_pct / 100
    if stake > budget:
        return RuleResult(
            name,
            False,
            f"{_money(stake, ccy)} is above the {lim.risk_per_trade_pct.normalize()}% per-trade "
            f"budget ({budget.quantize(CENT, rounding=ROUND_DOWN)} {ccy} of a "
            f"{_money(c.balance, ccy)} balance) — lower the stake or raise risk per trade",
        )
    quote = c.stake_quote
    full_range = quote is not None and quote.stake_min is not None and quote.stake_max is not None
    # Deriv refuses to price a stake outside its limits, so a price for this exact
    # stake proves it acceptable even when the reply lists only part of the range
    # (seen live on frxUSDJPY Rise/Fall, 2026-10-12). No price at all: fail closed.
    if quote is None or (not full_range and quote.ask_price is None):
        why = f" ({quote.detail})" if quote is not None and quote.detail else ""
        return RuleResult(
            name, False, f"the broker did not report its stake limits for this contract{why}"
        )
    if (quote.stake_min is not None and stake < quote.stake_min) or (
        quote.stake_max is not None and stake > quote.stake_max
    ):
        lo = _money(quote.stake_min, ccy) if quote.stake_min is not None else "?"
        hi = _money(quote.stake_max, ccy) if quote.stake_max is not None else "?"
        return RuleResult(
            name, False, f"{_money(stake, ccy)} is outside the broker's stake range {lo}–{hi}"
        )
    payout = (
        f", pays {_money(quote.payout, ccy)} if it wins"
        if quote.payout is not None and spec.contract_family is ContractFamily.RISE_FALL
        else ""
    )
    label = " (simulated)" if quote.simulated else ""
    return RuleResult(
        name,
        True,
        f"{_money(stake, ccy)} at risk{payout}; "
        + (
            f"broker range {_money(quote.stake_min, ccy)}–{_money(quote.stake_max, ccy)}"  # type: ignore[arg-type]
            if full_range
            else "the broker priced this stake"
        )
        + label,
    )


def multiplier_amounts(
    s: SignalIntent, c: RiskContext, stake: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """The limit_order money amounts a Multiplier will be bought with — exactly what
    the broker adapter sends: the assignment's own amounts, else the strategy's stop
    and target PRICES converted from the current entry price."""
    spec = c.contract
    if spec.stop_loss_amount is not None or spec.take_profit_amount is not None:
        return spec.stop_loss_amount, spec.take_profit_amount
    entry = s.entry_price
    if c.quote is not None:
        entry = c.quote.ask if s.side is Side.BUY else c.quote.bid
    return multiplier_limit_amounts(
        s.side, stake, spec.multiplier or 1, entry, s.stop_loss, s.take_profit
    )


def rule_multiplier_limits(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    """A Multiplier's stop loss / take profit must fit the broker's limits.

    The loss at the stop is at most the stake (a stop beyond the stake is left to
    the broker's stop out, which closes the contract at a loss of the stake), and
    the stake already fits the per-trade budget. Amounts outside the broker's
    range (Deriv: validation_params.stop_loss / take_profit) are refused here
    with the reason instead of being sent and refused by the broker.
    """
    name = "Stop/target amounts"
    ccy = c.account_currency
    stake = resolved_stake(c, lim)
    stop, take = multiplier_amounts(s, c, stake)
    q = c.stake_quote
    problems = []
    if stop is not None and q is not None:
        if q.stop_loss_min is not None and stop < q.stop_loss_min:
            problems.append(
                f"stop loss {_money(stop, ccy)} is below the broker's minimum "
                f"{_money(q.stop_loss_min, ccy)} — the stop is too close for this stake and "
                "multiplier"
            )
        if q.stop_loss_max is not None and stop > q.stop_loss_max:
            problems.append(
                f"stop loss {_money(stop, ccy)} is above the broker's maximum "
                f"{_money(q.stop_loss_max, ccy)}"
            )
    if take is not None and q is not None:
        if q.take_profit_min is not None and take < q.take_profit_min:
            problems.append(
                f"take profit {_money(take, ccy)} is below the broker's minimum "
                f"{_money(q.take_profit_min, ccy)}"
            )
        if q.take_profit_max is not None and take > q.take_profit_max:
            problems.append(
                f"take profit {_money(take, ccy)} is above the broker's maximum "
                f"{_money(q.take_profit_max, ccy)}"
            )
    if problems:
        return RuleResult(name, False, "; ".join(problems))
    reported = q is not None and q.stop_loss_min is not None
    stop_text = (
        f"stop loss {_money(stop, ccy)}"
        if stop is not None
        else f"no stop amount (loss bounded by the stake {_money(stake, ccy)} via stop out)"
    )
    take_text = f", take profit {_money(take, ccy)}" if take is not None else ", no take profit"
    return RuleResult(
        name,
        True,
        stop_text
        + take_text
        + ("" if reported else " (broker range not reported; the broker checks it when buying)"),
    )


def rule_open_risk(stake: Decimal, c: RiskContext, lim: RiskLimits) -> RuleResult:
    """Total money at risk (open trades + this stake) as % of equity."""
    if lim.max_total_risk_pct is None:
        return RuleResult("Total exposure", True, "no limit")
    if any(p.risk_amount is None for p in c.open_positions):
        return RuleResult("Total exposure", False, "risk of an open position is unknown")
    if c.equity is None or c.equity <= 0:
        return RuleResult("Total exposure", False, "equity unknown")
    open_risk = sum((p.risk_amount or Decimal(0) for p in c.open_positions), Decimal(0)) + stake
    pct = open_risk / c.equity * 100
    if pct > lim.max_total_risk_pct:
        return RuleResult(
            "Total exposure", False, f"open risk {_pct(pct)} > max {_pct(lim.max_total_risk_pct)}"
        )
    return RuleResult("Total exposure", True, f"open risk {_pct(pct)} after this trade")


def _run_rule(rule: Rule, signal: SignalIntent, ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """A rule that cannot be evaluated (malformed input) FAILS instead of crashing."""
    try:
        return rule(signal, ctx, limits)
    except (ArithmeticError, TypeError, ValueError, AttributeError) as exc:
        name = rule.__name__.removeprefix("rule_").replace("_", " ").capitalize()
        return RuleResult(name, False, f"could not be evaluated ({type(exc).__name__})")


def check_requested_volume(
    requested: Decimal, s: SignalIntent, c: RiskContext, lim: RiskLimits
) -> Sizing:
    """A person chose the volume: accept it only if it fits the broker's volume
    rules AND risks no more than the per-trade budget. Never adjusted upwards."""
    suggestion = size_position(s, c, lim)
    sym = c.symbol
    if requested <= 0:
        return Sizing(None, None, "volume must be positive")
    if requested < sym.volume_min or requested > sym.volume_max:
        return Sizing(
            None,
            None,
            f"{requested} lots is outside the broker range "
            f"{sym.volume_min.normalize()}–{sym.volume_max.normalize()}",
        )
    if (requested / sym.volume_step) % 1 != 0:
        return Sizing(None, None, f"volume must be a multiple of {sym.volume_step.normalize()}")
    if lim.max_position_lots is not None and requested > lim.max_position_lots:
        return Sizing(None, None, f"{requested} lots > max {lim.max_position_lots} per position")
    pv = point_value(sym, c.account_currency, c.quote_lookup)
    if pv is None or pv <= 0 or c.equity is None or c.equity <= 0:
        return Sizing(None, None, suggestion.detail)
    risk = (requested * (s.risk_distance / sym.point) * pv).quantize(Decimal("0.01"))
    budget = c.equity * lim.risk_per_trade_pct / 100
    if risk > budget:
        hint = (
            f"; the most you can trade is {suggestion.volume} lots"
            if suggestion.volume is not None
            else ""
        )
        return Sizing(
            None,
            None,
            f"{requested.normalize()} lots would risk {risk} {c.account_currency}, above the "
            f"{lim.risk_per_trade_pct.normalize()}% budget of {budget:.2f}{hint}",
        )
    return Sizing(
        requested.normalize(),
        risk,
        f"{requested.normalize()} lots risks {risk} {c.account_currency} (budget {budget:.2f})",
    )


def evaluate(
    signal: SignalIntent,
    ctx: RiskContext,
    limits: RiskLimits,
    *,
    requested_volume: Decimal | None = None,
) -> RiskDecision:
    """Run every rule. With `requested_volume` (manual tickets) the person's
    volume is validated against the same budget instead of being computed."""
    checks = [_run_rule(rule, signal, ctx, limits) for rule in RULES]
    halt = any(c.rule == "Max drawdown" and not c.passed and "reached" in c.detail for c in checks)
    if not all(c.passed for c in checks):
        return RiskDecision(False, checks, halt_account=halt)
    if _is_contract(ctx):
        return _evaluate_contract(signal, ctx, limits, checks)
    try:
        sizing = (
            size_position(signal, ctx, limits)
            if requested_volume is None
            else check_requested_volume(requested_volume, signal, ctx, limits)
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        sizing = Sizing(None, None, f"could not be evaluated ({type(exc).__name__})")
    checks.append(RuleResult("Position size", sizing.volume is not None, sizing.detail))
    if sizing.volume is None or sizing.risk_amount is None:
        return RiskDecision(False, checks)
    checks.append(rule_symbol_exposure(sizing.volume, ctx, limits))
    checks.append(rule_exposure(sizing.volume, sizing.risk_amount, ctx, limits))
    checks.append(rule_margin(sizing.volume, ctx))
    if not all(c.passed for c in checks):
        return RiskDecision(False, checks)
    slippage = None
    if limits.max_slippage_pips is not None:
        slippage = int(limits.max_slippage_pips * ctx.symbol.pip_size / ctx.symbol.point)
    return RiskDecision(True, checks, sizing.volume, sizing.risk_amount, slippage)


def _evaluate_contract(
    signal: SignalIntent, ctx: RiskContext, limits: RiskLimits, checks: list[RuleResult]
) -> RiskDecision:
    """Stake sizing: one contract, risking exactly its stake."""
    try:
        checks.append(rule_stake(ctx, limits))
        if checks[-1].passed and ctx.contract.contract_family is ContractFamily.MULTIPLIER:
            checks.append(rule_multiplier_limits(signal, ctx, limits))
        if checks[-1].passed:
            checks.append(rule_open_risk(resolved_stake(ctx, limits), ctx, limits))
    except (ArithmeticError, TypeError, ValueError, AttributeError) as exc:
        detail = f"could not be evaluated ({type(exc).__name__})"
        checks.append(RuleResult("Stake", False, detail))
    if not all(c.passed for c in checks):
        return RiskDecision(False, checks)
    stake = resolved_stake(ctx, limits).quantize(Decimal("0.01"))
    order = ContractOrder.build(ctx.contract, signal.side, stake)
    payout = ctx.stake_quote.payout if ctx.stake_quote is not None else None
    return RiskDecision(True, checks, Decimal(1), stake, None, contract=order, payout=payout)
