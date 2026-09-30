"""Rule evaluation and position sizing.

`evaluate` is a pure function of (signal, context, limits) so live trading
and backtesting run the exact same checks. Callers assemble `RiskContext`
from their own state (database + broker live; simulation state in backtests).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from fxrobot.domain.market import Quote, Side, SymbolInfo
from fxrobot.domain.modes import AccountEnvironment, TradingMode, environment_permitted
from fxrobot.market_data.conversion import QuoteLookup, conversion_rate, point_value
from fxrobot.market_data.sessions import is_fx_market_open, session_at
from fxrobot.risk_engine.limits import RiskLimits
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
    mode: TradingMode
    kill_switch_engaged: bool
    live_trading_locked: bool
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

    @property
    def rejection_reason(self) -> str | None:
        failed = next((c for c in self.checks if not c.passed), None)
        return None if failed is None else f"{failed.rule}: {failed.detail}"

    def checks_json(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.checks]


Rule = Callable[[SignalIntent, RiskContext, RiskLimits], RuleResult]


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def _pips(distance: Decimal, symbol: SymbolInfo) -> Decimal:
    return (abs(distance) / symbol.pip_size).quantize(Decimal("0.1"))


# ── individual rules (each pure, each explainable) ───────────────────────


def rule_kill_switch(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    return RuleResult(
        "Kill switch",
        not c.kill_switch_engaged,
        "STOP ALL TRADING is engaged" if c.kill_switch_engaged else "released",
    )


def rule_mode(_: SignalIntent, c: RiskContext, __: RiskLimits) -> RuleResult:
    ok = environment_permitted(c.mode, c.account_environment)
    if ok and c.account_environment is AccountEnvironment.LIVE and c.live_trading_locked:
        return RuleResult("Operating mode", False, "LIVE account but the LIVE hard lock is on")
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


def rule_stop_loss(s: SignalIntent, _: RiskContext, __: RiskLimits) -> RuleResult:
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
    if c.check_market_hours and not is_fx_market_open(c.now):
        return RuleResult("Market open", False, "FX market is closed (weekend)")
    return RuleResult("Market open", True, "open")


def rule_session(_: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    session = session_at(c.now).value
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
    if lim.max_spread_pips is not None and spread > lim.max_spread_pips:
        return RuleResult("Spread", False, f"{spread} pips > max {lim.max_spread_pips}")
    return RuleResult("Spread", True, f"{spread} pips")


def rule_stop_distance(s: SignalIntent, c: RiskContext, lim: RiskLimits) -> RuleResult:
    pips = _pips(s.risk_distance, c.symbol)
    if lim.min_stop_pips is not None and pips < lim.min_stop_pips:
        return RuleResult("Stop distance", False, f"{pips} pips < min {lim.min_stop_pips}")
    if lim.max_stop_pips is not None and pips > lim.max_stop_pips:
        return RuleResult("Stop distance", False, f"{pips} pips > max {lim.max_stop_pips}")
    return RuleResult("Stop distance", True, f"{pips} pips")


def rule_reward_risk(s: SignalIntent, _: RiskContext, lim: RiskLimits) -> RuleResult:
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
    rule_mode,
    rule_account_enabled,
    rule_broker,
    rule_stop_loss,
    rule_data_fresh,
    rule_market_open,
    rule_session,
    rule_spread,
    rule_stop_distance,
    rule_reward_risk,
    rule_daily_loss,
    rule_weekly_loss,
    rule_drawdown,
    rule_cooldown,
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
    if rate is None:
        return RuleResult("Margin", False, f"cannot value {c.symbol.base_currency} exposure")
    required = volume * c.symbol.contract_size * rate / Decimal(c.leverage)
    if required > c.free_margin:
        return RuleResult("Margin", False, f"needs {required:.2f}, free {c.free_margin:.2f}")
    return RuleResult("Margin", True, f"needs {required:.2f} of {c.free_margin:.2f} free")


def evaluate(signal: SignalIntent, ctx: RiskContext, limits: RiskLimits) -> RiskDecision:
    checks = [rule(signal, ctx, limits) for rule in RULES]
    halt = any(c.rule == "Max drawdown" and not c.passed and "reached" in c.detail for c in checks)
    if not all(c.passed for c in checks):
        return RiskDecision(False, checks, halt_account=halt)
    sizing = size_position(signal, ctx, limits)
    checks.append(RuleResult("Position size", sizing.volume is not None, sizing.detail))
    if sizing.volume is None or sizing.risk_amount is None:
        return RiskDecision(False, checks)
    checks.append(rule_exposure(sizing.volume, sizing.risk_amount, ctx, limits))
    checks.append(rule_margin(sizing.volume, ctx))
    if not all(c.passed for c in checks):
        return RiskDecision(False, checks)
    slippage = None
    if limits.max_slippage_pips is not None:
        slippage = int(limits.max_slippage_pips * ctx.symbol.pip_size / ctx.symbol.point)
    return RiskDecision(True, checks, sizing.volume, sizing.risk_amount, slippage)
