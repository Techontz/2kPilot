"""Pure unit tests of the risk engine (`fxrobot.risk_engine`).

A helper builds a signal + context that the default limits APPROVE; each test
then flips exactly one condition and proves the matching rule rejects with a
clear reason. No database is touched.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fxrobot.domain.contracts import ContractFamily, ContractSpec
from fxrobot.domain.market import Quote, Side, SymbolInfo, Timeframe
from fxrobot.domain.modes import AccountEnvironment, TradingMode
from fxrobot.risk_engine import DEFAULT_LIMITS, RiskContext, RiskDecision, RiskLimits, evaluate
from fxrobot.risk_engine.engine import RULES, OpenExposure
from fxrobot.strategy_engine.base import SignalIntent

# Wednesday 2026-09-30 10:00:30 UTC — LONDON session, market open.
NOW = datetime(2026, 9, 30, 10, 0, 30, tzinfo=UTC)
D = Decimal

EURUSD = SymbolInfo(
    name="EURUSD",
    description="Euro vs US Dollar",
    base_currency="EUR",
    quote_currency="USD",
    digits=5,
    point=D("0.00001"),
    contract_size=D(100000),
    volume_min=D("0.01"),
    volume_max=D(50),
    volume_step=D("0.01"),
    trade_allowed=True,
)
USDJPY = SymbolInfo(
    name="USDJPY",
    description="US Dollar vs Yen",
    base_currency="USD",
    quote_currency="JPY",
    digits=3,
    point=D("0.001"),
    contract_size=D(100000),
    volume_min=D("0.01"),
    volume_max=D(50),
    volume_step=D("0.01"),
    trade_allowed=True,
)


def quote(symbol: str, bid: str, ask: str, at: datetime = NOW - timedelta(seconds=5)) -> Quote:
    return Quote(symbol, D(bid), D(ask), at)


def lookup_from(*quotes: Quote) -> Any:
    table = {q.symbol: q for q in quotes}
    return table.get


def make_signal(now: datetime = NOW, **overrides: Any) -> SignalIntent:
    """BUY EURUSD: entry 1.10010, 20-pip stop, 60-pip target (RR 3)."""
    # Signal bar: the M15 bar that closed at the most recent quarter hour before `now`.
    bar_close = Timeframe.M15.floor(now)
    values: dict[str, Any] = {
        "side": Side.BUY,
        "timeframe": Timeframe.M15,
        "bar_time": bar_close - Timeframe.M15.delta,
        "entry_price": D("1.10010"),
        "stop_loss": D("1.09810"),
        "take_profit": D("1.10610"),
        "reasons": ["test"],
    }
    values.update(overrides)
    return SignalIntent(**values)


def make_context(now: datetime = NOW, **overrides: Any) -> RiskContext:
    q = quote("EURUSD", "1.10000", "1.10010", now - timedelta(seconds=5))
    values: dict[str, Any] = {
        "now": now,
        "mode": TradingMode.DEMO,
        "kill_switch_engaged": False,
        "platform_halted": False,
        "live_trading_locked": True,
        "live_authorized": False,
        "account_environment": AccountEnvironment.DEMO,
        "account_trading_enabled": True,
        "broker_connected": True,
        "account_currency": "USD",
        "balance": D(10000),
        "equity": D(10000),
        "free_margin": D(10000),
        "leverage": 100,
        "symbol": EURUSD,
        "quote": q,
        "quote_lookup": lookup_from(q),
        "start_of_day_balance": D(10000),
        "start_of_week_balance": D(10000),
        "peak_equity": D(10000),
    }
    values.update(overrides)
    return RiskContext(**values)


def run(
    signal: SignalIntent | None = None,
    ctx: RiskContext | None = None,
    limits: RiskLimits = DEFAULT_LIMITS,
) -> RiskDecision:
    return evaluate(signal or make_signal(), ctx or make_context(), limits)


def assert_rejected(decision: RiskDecision, rule: str, fragment: str) -> None:
    assert decision.approved is False
    assert decision.volume is None
    assert decision.risk_amount is None
    reason = decision.rejection_reason
    assert reason is not None
    assert reason.startswith(f"{rule}: "), reason
    assert fragment in reason, reason


def check(decision: RiskDecision, rule: str) -> Any:
    return next(c for c in decision.checks if c.rule == rule)


# ── baseline ────────────────────────────────────────────────────────────


def test_baseline_is_approved_with_exact_size() -> None:
    decision = run()
    assert decision.approved is True, decision.rejection_reason
    assert decision.rejection_reason is None
    # 0.5% of 10 000 = 50 USD; 20 pips = 200 points x 1 USD/point/lot = 200 USD/lot.
    assert decision.volume == D("0.25")
    assert decision.risk_amount == D("50.00")
    assert decision.max_slippage_points == 15  # 1.5 pips on a 5-digit quote
    assert decision.halt_account is False
    assert len(decision.checks) == len(RULES) + 4
    assert all(c.passed for c in decision.checks)
    assert [c.rule for c in decision.checks[-4:]] == [
        "Position size",
        "Symbol exposure",
        "Total exposure",
        "Margin",
    ]


def test_checks_json_serialises_every_rule() -> None:
    decision = run()
    rows = decision.checks_json()
    assert rows[0] == {"rule": "Kill switch", "passed": True, "detail": "released"}
    assert all(set(r) == {"rule", "passed", "detail"} for r in rows)


def test_rejection_still_records_every_rule() -> None:
    decision = run(ctx=make_context(kill_switch_engaged=True, broker_connected=False))
    assert len(decision.checks) == len(RULES)  # sizing is skipped after a rule failure
    failed = [c.rule for c in decision.checks if not c.passed]
    assert failed == ["Kill switch", "Broker connected"]
    assert decision.rejection_reason == "Kill switch: STOP ALL TRADING is engaged"


def test_approved_sell_signal() -> None:
    signal = make_signal(
        side=Side.SELL,
        entry_price=D("1.10000"),
        stop_loss=D("1.10200"),
        take_profit=D("1.09400"),
    )
    decision = run(signal)
    assert decision.approved is True, decision.rejection_reason
    assert decision.volume == D("0.25")


def test_no_slippage_limit_gives_none() -> None:
    decision = run(limits=replace(DEFAULT_LIMITS, max_slippage_pips=None))
    assert decision.approved is True
    assert decision.max_slippage_points is None


# ── switches, mode, account, broker ─────────────────────────────────────


def test_kill_switch_rejects() -> None:
    assert_rejected(run(ctx=make_context(kill_switch_engaged=True)), "Kill switch", "STOP ALL")


def test_platform_halt_rejects_even_with_the_users_switch_released() -> None:
    decision = run(ctx=make_context(platform_halted=True, kill_switch_engaged=False))
    assert_rejected(decision, "Kill switch", "halted platform-wide")


@pytest.mark.parametrize(
    ("mode", "env", "locked", "fragment"),
    [
        (TradingMode.DEMO, AccountEnvironment.LIVE, False, "LIVE account not allowed in DEMO"),
        (TradingMode.DEMO, AccountEnvironment.UNKNOWN, False, "UNKNOWN account not allowed"),
        (TradingMode.LIVE, AccountEnvironment.UNKNOWN, False, "UNKNOWN account not allowed"),
        (TradingMode.LIVE, AccountEnvironment.DEMO, False, "DEMO account not allowed in LIVE"),
        (TradingMode.LIVE, AccountEnvironment.LIVE, True, "LIVE hard lock is on"),
        (TradingMode.LIVE, AccountEnvironment.LIVE, False, "not been authorised"),
    ],
)
def test_mode_environment_rejections(
    mode: TradingMode, env: AccountEnvironment, locked: bool, fragment: str
) -> None:
    ctx = make_context(mode=mode, account_environment=env, live_trading_locked=locked)
    assert_rejected(run(ctx=ctx), "Operating mode", fragment)


@pytest.mark.parametrize(
    ("mode", "env", "locked"),
    [
        (TradingMode.DEMO, AccountEnvironment.PAPER, True),
        (TradingMode.DEMO, AccountEnvironment.DEMO, True),
        (TradingMode.DEMO, AccountEnvironment.DEMO, False),  # lock only guards LIVE accounts
        (TradingMode.LIVE, AccountEnvironment.LIVE, False),
    ],
)
def test_mode_environment_allowed(mode: TradingMode, env: AccountEnvironment, locked: bool) -> None:
    ctx = make_context(
        mode=mode, account_environment=env, live_trading_locked=locked, live_authorized=True
    )
    decision = run(ctx=ctx)
    assert decision.approved is True, decision.rejection_reason


def test_account_disabled_rejects() -> None:
    decision = run(ctx=make_context(account_trading_enabled=False))
    assert_rejected(decision, "Account trading enabled", "disabled")


def test_broker_disconnected_rejects() -> None:
    assert_rejected(run(ctx=make_context(broker_connected=False)), "Broker connected", "disconn")


# ── stop loss ───────────────────────────────────────────────────────────


def test_zero_stop_loss_rejects() -> None:
    decision = run(make_signal(stop_loss=D(0)))
    assert_rejected(decision, "Stop loss required", "no stop loss")


def test_missing_stop_loss_rejects_without_crashing() -> None:
    decision = run(make_signal(stop_loss=None))
    assert_rejected(decision, "Stop loss required", "no stop loss")
    # Rules that depend on the stop fail too (never crash): no stop = zero distance.
    distance = check(decision, "Stop distance")
    assert distance.passed is False


def test_buy_stop_above_entry_rejects() -> None:
    decision = run(make_signal(stop_loss=D("1.10210")))
    assert_rejected(decision, "Stop loss required", "wrong side")


def test_sell_stop_below_entry_rejects() -> None:
    signal = make_signal(
        side=Side.SELL, entry_price=D("1.10000"), stop_loss=D("1.09800"), take_profit=D("1.094")
    )
    assert_rejected(run(signal), "Stop loss required", "wrong side")


def test_stop_equal_to_entry_rejects() -> None:
    decision = run(make_signal(stop_loss=D("1.10010")))
    assert_rejected(decision, "Stop loss required", "wrong side")


# ── data freshness, market hours, sessions ──────────────────────────────


def test_missing_quote_rejects() -> None:
    assert_rejected(run(ctx=make_context(quote=None)), "Market data fresh", "no current price")


def test_stale_quote_rejects() -> None:
    old = quote("EURUSD", "1.10000", "1.10010", NOW - timedelta(seconds=121))
    assert_rejected(run(ctx=make_context(quote=old)), "Market data fresh", "121s old (max 120s)")


def test_quote_at_max_age_is_fresh() -> None:
    edge = quote("EURUSD", "1.10000", "1.10010", NOW - timedelta(seconds=120))
    assert run(ctx=make_context(quote=edge)).approved is True


def test_stale_signal_bar_rejects() -> None:
    # Bar 09:30 closed 09:45 → 930 s before NOW; M15 allows half a bar (450 s).
    signal = make_signal(bar_time=datetime(2026, 9, 30, 9, 30, tzinfo=UTC))
    assert_rejected(run(signal), "Market data fresh", "signal bar closed 930s ago (max 450s)")


def test_future_signal_bar_rejects() -> None:
    # The bar that is still forming (closes 10:15) must never be traded on.
    signal = make_signal(bar_time=datetime(2026, 9, 30, 10, 0, tzinfo=UTC))
    assert_rejected(run(signal), "Market data fresh", "signal bar closed -")


def test_weekend_rejects() -> None:
    saturday = datetime(2026, 10, 3, 10, 0, 30, tzinfo=UTC)
    decision = run(make_signal(saturday), make_context(saturday))
    assert_rejected(decision, "Market open", "weekend")


def test_weekend_allowed_when_market_hours_check_disabled() -> None:
    saturday = datetime(2026, 10, 3, 10, 0, 30, tzinfo=UTC)
    decision = run(make_signal(saturday), make_context(saturday, check_market_hours=False))
    assert decision.approved is True, decision.rejection_reason


def test_friday_after_close_rejects() -> None:
    friday = datetime(2026, 10, 2, 21, 0, 30, tzinfo=UTC)
    limits = replace(DEFAULT_LIMITS, allowed_sessions=())
    decision = run(make_signal(friday), make_context(friday), limits)
    assert_rejected(decision, "Market open", "closed")


def test_session_not_allowed_rejects() -> None:
    asia = datetime(2026, 9, 30, 3, 0, 30, tzinfo=UTC)
    decision = run(make_signal(asia), make_context(asia))
    assert_rejected(decision, "Trading session", "ASIA session not allowed")


R_75 = replace(
    EURUSD,
    name="R_75",
    description="Volatility 75 Index",
    base_currency="R_75",
    digits=4,
    point=D("0.0001"),
    contract_size=D(1),
    category="synthetic",
)


@pytest.mark.parametrize(
    "contract",
    [
        ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=50),
        ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=5, duration_unit="m"),
    ],
)
def test_synthetic_contracts_skip_fx_sessions_and_pip_spreads(contract: ContractSpec) -> None:
    """Seen live (2026-10): every R_75 signal was refused for the ASIA session and an
    8-point spread read as "80000.0 pips > max 2.50" — both forex measures."""
    asia = datetime(2026, 10, 12, 1, 5, 30, tzinfo=UTC)
    q = quote("R_75", "41477.928", "41485.928", asia - timedelta(seconds=5))
    ctx = make_context(asia, symbol=R_75, quote=q, quote_lookup=lookup_from(q), contract=contract)
    decision = run(make_signal(asia), ctx)
    assert check(decision, "Trading session").passed
    assert "around the clock" in check(decision, "Trading session").detail
    assert check(decision, "Spread").passed


def test_synthetic_spot_trades_still_check_the_spread() -> None:
    q = quote("R_75", "41477.928", "41485.928")
    decision = run(ctx=make_context(symbol=R_75, quote=q, quote_lookup=lookup_from(q)))
    assert_rejected(decision, "Spread", "80000.0 pips > max 2.5")


def test_empty_allowed_sessions_allows_any_session() -> None:
    asia = datetime(2026, 9, 30, 3, 0, 30, tzinfo=UTC)
    limits = replace(DEFAULT_LIMITS, allowed_sessions=())
    assert run(make_signal(asia), make_context(asia), limits).approved is True


# ── spread, stop distance, reward/risk ──────────────────────────────────


def test_wide_spread_rejects() -> None:
    wide = quote("EURUSD", "1.10000", "1.10030")
    assert_rejected(run(ctx=make_context(quote=wide)), "Spread", "3.0 pips > max 2.5")


def test_spread_at_max_passes() -> None:
    edge = quote("EURUSD", "1.10000", "1.10025")
    decision = run(ctx=make_context(quote=edge))
    assert decision.approved is True
    assert check(decision, "Spread").detail == "2.5 pips"


def test_stop_below_min_pips_rejects() -> None:
    signal = make_signal(stop_loss=D("1.09940"), take_profit=D("1.10610"))  # 7 pips
    assert_rejected(run(signal), "Stop distance", "7.0 pips < min 8")


def test_stop_above_max_pips_rejects() -> None:
    signal = make_signal(stop_loss=D("1.08500"), take_profit=D("1.13500"))  # 151 pips
    assert_rejected(run(signal), "Stop distance", "151.0 pips > max 150")


def test_reward_risk_below_min_rejects() -> None:
    signal = make_signal(take_profit=D("1.10290"))  # 28 / 20 = 1.4
    assert_rejected(run(signal), "Reward/risk", "1:1.40 < min 1:1.5")


def test_missing_take_profit_rejects_when_min_rr_set() -> None:
    assert_rejected(run(make_signal(take_profit=None)), "Reward/risk", "no take profit")


def test_missing_take_profit_allowed_without_min_rr() -> None:
    limits = replace(DEFAULT_LIMITS, min_reward_risk=None)
    decision = run(make_signal(take_profit=None), limits=limits)
    assert decision.approved is True
    assert check(decision, "Reward/risk").detail == "no minimum"


# ── loss limits, drawdown, cooldown ─────────────────────────────────────


def test_daily_loss_limit_reached_rejects() -> None:
    decision = run(ctx=make_context(realized_pnl_today=D(-200)))
    assert_rejected(decision, "Daily loss limit", "loss 2.00% reached limit 2.00%")
    assert decision.halt_account is False


def test_daily_loss_just_below_limit_passes() -> None:
    decision = run(ctx=make_context(realized_pnl_today=D(-199)))
    assert decision.approved is True
    assert check(decision, "Daily loss limit").detail == "loss 1.99% of 2.00%"


def test_daily_loss_includes_unrealized() -> None:
    ctx = make_context(realized_pnl_today=D(-100), unrealized_pnl=D(-100))
    assert_rejected(run(ctx=ctx), "Daily loss limit", "reached")


def test_daily_profit_does_not_count_as_loss() -> None:
    decision = run(ctx=make_context(realized_pnl_today=D(500)))
    assert check(decision, "Daily loss limit").detail == "loss 0.00% of 2.00%"


def test_daily_loss_unknown_reference_balance_rejects() -> None:
    ctx = make_context(start_of_day_balance=None)
    assert_rejected(run(ctx=ctx), "Daily loss limit", "reference balance unknown")


def test_daily_loss_disabled_passes_without_reference() -> None:
    limits = replace(DEFAULT_LIMITS, max_daily_loss_pct=None)
    decision = run(ctx=make_context(start_of_day_balance=None), limits=limits)
    assert decision.approved is True


def test_weekly_loss_limit_reached_rejects() -> None:
    decision = run(ctx=make_context(realized_pnl_week=D(-400)))
    assert_rejected(decision, "Weekly loss limit", "loss 4.00% reached limit 4.00%")


def test_weekly_loss_includes_unrealized() -> None:
    # -250 realized this week + -150 open = 4% (daily: only the -150 open = 1.5%, passes).
    ctx = make_context(realized_pnl_week=D(-250), unrealized_pnl=D(-150))
    decision = run(ctx=ctx)
    assert check(decision, "Daily loss limit").passed
    assert_rejected(decision, "Weekly loss limit", "loss 4.00% reached limit 4.00%")


def test_drawdown_limit_reached_halts_account() -> None:
    ctx = make_context(equity=D(9000), peak_equity=D(10000))
    decision = run(ctx=ctx)
    assert_rejected(decision, "Max drawdown", "drawdown 10.00% reached limit 10.00%")
    assert decision.halt_account is True


def test_drawdown_below_limit_passes() -> None:
    ctx = make_context(equity=D(9001), peak_equity=D(10000))
    decision = run(ctx=ctx)
    assert check(decision, "Max drawdown").passed
    assert decision.halt_account is False


def test_drawdown_unknown_equity_rejects_without_halt() -> None:
    decision = run(ctx=make_context(peak_equity=None))
    assert_rejected(decision, "Max drawdown", "equity history unknown")
    assert decision.halt_account is False


def test_cooldown_active_rejects() -> None:
    ctx = make_context(consecutive_losses=3, last_loss_at=NOW - timedelta(minutes=60))
    decision = run(ctx=ctx)
    assert_rejected(decision, "Loss cooldown", "3 losses in a row")
    assert "181 more min" in (decision.rejection_reason or "")


def test_cooldown_expired_passes() -> None:
    ctx = make_context(consecutive_losses=3, last_loss_at=NOW - timedelta(minutes=241))
    assert run(ctx=ctx).approved is True


def test_cooldown_below_loss_count_passes() -> None:
    ctx = make_context(consecutive_losses=2, last_loss_at=NOW - timedelta(minutes=1))
    assert run(ctx=ctx).approved is True


def test_cooldown_disabled_passes() -> None:
    ctx = make_context(consecutive_losses=10, last_loss_at=NOW)
    limits = replace(DEFAULT_LIMITS, cooldown_after_losses=None)
    decision = run(ctx=ctx, limits=limits)
    assert decision.approved is True
    assert check(decision, "Loss cooldown").detail == "no cooldown"


# ── trade counts and positions ──────────────────────────────────────────


def test_trades_per_day_limit_rejects() -> None:
    assert_rejected(run(ctx=make_context(trades_today=20)), "Trades per day", "20 of 20 used")


def test_trades_per_day_below_limit_passes() -> None:
    assert run(ctx=make_context(trades_today=19)).approved is True


def pos(symbol: str, volume: str = "0.10", risk: str | None = "10") -> OpenExposure:
    return OpenExposure(symbol, Side.BUY, D(volume), None if risk is None else D(risk))


def test_max_open_positions_rejects() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD"), pos("USDJPY"), pos("AUDUSD")])
    assert_rejected(run(ctx=ctx), "Open positions", "3 open (max 3)")


def test_max_positions_per_symbol_rejects() -> None:
    ctx = make_context(open_positions=[pos("EURUSD")])
    assert_rejected(run(ctx=ctx), "Open positions", "1 open on EURUSD (max 1)")


def test_open_positions_below_limits_pass() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD"), pos("USDJPY")])
    decision = run(ctx=ctx)
    assert decision.approved is True
    assert check(decision, "Open positions").detail == "2 open, 0 on EURUSD"


# ── sizing ──────────────────────────────────────────────────────────────


def test_sizing_scales_with_risk_percent() -> None:
    limits = replace(DEFAULT_LIMITS, risk_per_trade_pct=D(1))
    decision = run(limits=limits)
    assert decision.volume == D("0.5")
    assert decision.risk_amount == D("100.00")


def test_sizing_usdjpy_converts_through_quote_lookup() -> None:
    q = quote("USDJPY", "150.000", "150.010")
    ctx = make_context(symbol=USDJPY, quote=q, quote_lookup=lookup_from(q))
    signal = make_signal(entry_price=D("150.010"), stop_loss=D("149.810"), take_profit=D("150.610"))
    decision = run(signal, ctx)
    assert decision.approved is True, decision.rejection_reason
    # Point value = 100000 x 0.001 / 150.005 (mid) USD. 200 points → ~133.33 USD/lot.
    # Budget 50 USD → 0.375 lots → rounded DOWN to 0.37.
    assert decision.volume == D("0.37")
    expected_risk = (D("0.37") * 200 * 100000 * D("0.001") / D("150.005")).quantize(D("0.01"))
    assert decision.risk_amount == expected_risk == D("49.33")
    assert decision.max_slippage_points == 15


def test_sizing_rounds_down_never_up() -> None:
    # Budget 51.80 / 200 per lot = 0.259 lots → 0.25, never 0.26.
    decision = run(ctx=make_context(equity=D(10360), peak_equity=D(10360)))
    assert decision.volume == D("0.25")
    assert decision.risk_amount == D("50.00")
    assert decision.risk_amount <= D(10360) * D("0.005")


def test_sizing_rounds_down_to_coarse_step() -> None:
    symbol = replace(EURUSD, volume_step=D("0.1"), volume_min=D("0.1"))
    decision = run(ctx=make_context(symbol=symbol))
    assert decision.volume == D("0.2")
    assert decision.risk_amount == D("40.00")


def test_sizing_capped_by_max_position_lots() -> None:
    ctx = make_context(equity=D(1_000_000), peak_equity=D(1_000_000), free_margin=D(1_000_000))
    limits = replace(DEFAULT_LIMITS, risk_per_trade_pct=D(5), max_total_risk_pct=None)
    decision = run(ctx=ctx, limits=limits)
    assert decision.approved is True, decision.rejection_reason
    assert decision.volume == D(1)
    assert decision.risk_amount == D("200.00")


def test_sizing_capped_by_symbol_volume_max() -> None:
    symbol = replace(EURUSD, volume_max=D("0.15"))
    decision = run(ctx=make_context(symbol=symbol))
    assert decision.volume == D("0.15")
    assert decision.risk_amount == D("30.00")


def test_sizing_cap_without_max_position_lots_uses_volume_max() -> None:
    symbol = replace(EURUSD, volume_max=D("2.5"))
    ctx = make_context(symbol=symbol, equity=D(1_000_000), peak_equity=D(1_000_000), leverage=None)
    limits = replace(
        DEFAULT_LIMITS,
        risk_per_trade_pct=D(5),
        max_position_lots=None,
        max_symbol_exposure_lots=None,
        max_total_exposure_lots=None,
        max_total_risk_pct=None,
    )
    decision = run(ctx=ctx, limits=limits)
    assert decision.volume == D("2.5")


def test_sizing_below_volume_min_rejects() -> None:
    ctx = make_context(equity=D(100), peak_equity=D(100), free_margin=D(100))
    decision = run(ctx=ctx)
    assert_rejected(decision, "Position size", "below the minimum 0.01")
    assert "0.0025 lots" in (decision.rejection_reason or "")


def test_sizing_never_rounds_up_to_volume_min() -> None:
    # 0.009 lots worth of budget must NOT become 0.01 lots.
    ctx = make_context(equity=D(360), peak_equity=D(360), free_margin=D(360))
    decision = run(ctx=ctx)
    assert_rejected(decision, "Position size", "0.0090 lots")


def test_sizing_unknown_equity_rejects() -> None:
    limits = replace(DEFAULT_LIMITS, max_drawdown_pct=None)
    decision = run(ctx=make_context(equity=None), limits=limits)
    assert_rejected(decision, "Position size", "equity unknown")


def test_sizing_missing_conversion_rejects() -> None:
    q = quote("USDJPY", "150.000", "150.010")
    ctx = make_context(symbol=USDJPY, quote=q, quote_lookup=lookup_from())
    signal = make_signal(entry_price=D("150.010"), stop_loss=D("149.810"), take_profit=D("150.610"))
    assert_rejected(run(signal, ctx), "Position size", "cannot convert JPY to USD")


def test_sizing_uses_broker_point_value_when_given() -> None:
    symbol = replace(EURUSD, point_value=D(2))  # e.g. broker quotes 2 USD/point/lot
    decision = run(ctx=make_context(symbol=symbol))
    assert decision.volume == D("0.12")  # 50 / (200 x 2) = 0.125 → 0.12
    assert decision.risk_amount == D("48.00")


# ── exposure, margin ────────────────────────────────────────────────────


def test_total_exposure_lots_rejects() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD", "1.0"), pos("USDJPY", "1.0")])
    limits = replace(DEFAULT_LIMITS, max_total_exposure_lots=D(2))
    assert_rejected(run(ctx=ctx, limits=limits), "Total exposure", "2.25 lots > max 2")


def test_total_risk_at_limit_passes() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD", risk="75"), pos("USDJPY", risk="75")])
    decision = run(ctx=ctx)  # 150 + 50 = 200 = exactly 2% of 10 000
    assert decision.approved is True, decision.rejection_reason


def test_total_risk_over_limit_rejects() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD", risk="75"), pos("USDJPY", risk="76")])
    assert_rejected(run(ctx=ctx), "Total exposure", "open risk 2.01% > max 2.00%")


def test_unknown_open_position_risk_rejects() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD", risk=None)])
    assert_rejected(run(ctx=ctx), "Total exposure", "risk of an open position is unknown")


def test_unknown_open_position_risk_allowed_without_total_risk_limit() -> None:
    ctx = make_context(open_positions=[pos("GBPUSD", risk=None)])
    limits = replace(DEFAULT_LIMITS, max_total_risk_pct=None)
    assert run(ctx=ctx, limits=limits).approved is True


def test_margin_insufficient_rejects() -> None:
    # 0.25 lots x 100 000 EUR x 1.10005 / 100 = 275.01 USD needed.
    decision = run(ctx=make_context(free_margin=D(200)))
    assert_rejected(decision, "Margin", "needs 275.01, free 200.00")


def test_margin_sufficient_detail() -> None:
    assert check(run(), "Margin").detail == "needs 275.01 of 10000.00 free"


def test_margin_unknown_leverage_defers_to_broker() -> None:
    decision = run(ctx=make_context(leverage=None))
    assert decision.approved is True
    assert check(decision, "Margin").detail == "broker enforces margin"


def test_margin_missing_base_conversion_rejects() -> None:
    # Broker supplies point value (so sizing works) but EUR cannot be valued in GBP.
    symbol = replace(EURUSD, point_value=D(1))
    ctx = make_context(symbol=symbol, account_currency="GBP")
    assert_rejected(run(ctx=ctx), "Margin", "cannot value EUR exposure")


# ── RiskLimits ──────────────────────────────────────────────────────────


def test_limits_from_mapping_parses_types() -> None:
    limits = RiskLimits.from_mapping(
        {
            "risk_per_trade_pct": "1.25",
            "max_position_lots": 2,
            "max_open_positions": "4",
            "max_spread_pips": 3.5,
            "min_reward_risk": "2",
            "allowed_sessions": ["london", "overlap"],
            "cooldown_minutes": "30",
            "max_data_age_seconds": 60,
            "unknown_key": "ignored",
        }
    )
    assert limits.risk_per_trade_pct == D("1.25")
    assert limits.max_position_lots == D(2)
    assert limits.max_open_positions == 4
    assert limits.max_spread_pips == D("3.5")
    assert limits.min_reward_risk == D(2)
    assert limits.allowed_sessions == ("LONDON", "OVERLAP")
    assert limits.cooldown_minutes == 30
    assert limits.max_data_age_seconds == 60
    # Unspecified keys keep defaults.
    assert limits.max_drawdown_pct == DEFAULT_LIMITS.max_drawdown_pct


def test_limits_from_mapping_none_disables_optional_limit() -> None:
    limits = RiskLimits.from_mapping({"max_trades_per_day": None, "max_drawdown_pct": None})
    assert limits.max_trades_per_day is None
    assert limits.max_drawdown_pct is None


def test_limits_json_round_trip() -> None:
    assert RiskLimits.from_mapping(DEFAULT_LIMITS.as_json()) == DEFAULT_LIMITS
    data = DEFAULT_LIMITS.as_json()
    assert data["risk_per_trade_pct"] == "0.5"
    assert data["allowed_sessions"] == ["LONDON", "OVERLAP", "NEW_YORK"]
    assert data["max_trades_per_day"] == 20
    assert data["stake_amount"] == "1"
    assert data["max_consecutive_losses"] == 3


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"risk_per_trade_pct": "0"}, "risk_per_trade_pct"),
        ({"risk_per_trade_pct": "0.009"}, "risk_per_trade_pct"),
        ({"risk_per_trade_pct": "5.01"}, "risk_per_trade_pct"),
        ({"max_daily_loss_pct": "0"}, "max_daily_loss_pct"),
        ({"max_weekly_loss_pct": "-1"}, "max_weekly_loss_pct"),
        ({"max_drawdown_pct": "100.1"}, "max_drawdown_pct"),
        ({"max_total_risk_pct": "0"}, "max_total_risk_pct"),
        ({"min_stop_pips": "20", "max_stop_pips": "10"}, "min_stop_pips"),
        ({"max_data_age_seconds": 0}, "max_data_age_seconds"),
        ({"allowed_sessions": ["LONDON", "TOKYO"]}, "allowed_sessions"),
    ],
)
def test_limits_validation_rejects(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RiskLimits.from_mapping(data)


@pytest.mark.parametrize("pct", ["0.01", "5", "0.5"])
def test_limits_risk_pct_bounds_inclusive(pct: str) -> None:
    assert RiskLimits.from_mapping({"risk_per_trade_pct": pct}).risk_per_trade_pct == D(pct)


def test_limits_max_loss_pct_100_allowed() -> None:
    assert RiskLimits.from_mapping({"max_drawdown_pct": 100}).max_drawdown_pct == D(100)


def test_limits_equal_min_max_stop_allowed() -> None:
    limits = RiskLimits.from_mapping({"min_stop_pips": 10, "max_stop_pips": 10})
    assert limits.min_stop_pips == limits.max_stop_pips == D(10)


def test_limits_invalid_number_raises() -> None:
    with pytest.raises((ValueError, ArithmeticError)):
        RiskLimits.from_mapping({"max_spread_pips": "abc"})


def test_default_limits_are_valid() -> None:
    DEFAULT_LIMITS.validate()


# ── controls added with the Laravel migration ───────────────────────────


def test_trading_hours_window() -> None:
    inside = replace(DEFAULT_LIMITS, trading_hours_start="08:00", trading_hours_end="17:00")
    assert check(run(limits=inside), "Trading hours").passed
    outside = replace(DEFAULT_LIMITS, trading_hours_start="12:00", trading_hours_end="16:00")
    assert_rejected(run(limits=outside), "Trading hours", "10:00 UTC is outside 12:00–16:00 UTC")


def test_trading_hours_may_wrap_past_midnight() -> None:
    overnight = replace(DEFAULT_LIMITS, trading_hours_start="22:00", trading_hours_end="11:00")
    assert check(run(limits=overnight), "Trading hours").passed
    late = replace(DEFAULT_LIMITS, trading_hours_start="22:00", trading_hours_end="06:00")
    assert_rejected(run(limits=late), "Trading hours", "outside")


def test_trading_hours_validation() -> None:
    with pytest.raises(ValueError, match="both"):
        RiskLimits.from_mapping({"trading_hours_start": "08:00"})
    with pytest.raises(ValueError, match="HH:MM"):
        RiskLimits.from_mapping({"trading_hours_start": "8am", "trading_hours_end": "17:00"})


def test_symbol_exposure_limit() -> None:
    ctx = make_context(open_positions=[OpenExposure("EURUSD", Side.BUY, D("0.9"), D("10"))])
    limits = replace(
        DEFAULT_LIMITS, max_positions_per_symbol=None, max_symbol_exposure_lots=D("1.0")
    )
    assert_rejected(run(ctx=ctx, limits=limits), "Symbol exposure", "1.15 lots on EURUSD > max 1.0")
    other = make_context(open_positions=[OpenExposure("USDJPY", Side.BUY, D("0.9"), D("10"))])
    assert run(ctx=other, limits=limits).approved


def test_broker_reported_market_status_wins() -> None:
    weekend = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)  # Saturday: FX closed
    synthetic = replace(EURUSD, category="synthetic", market_open=True)
    ctx = make_context(now=weekend, symbol=synthetic)
    limits = replace(DEFAULT_LIMITS, allowed_sessions=())
    assert (
        check(run(make_signal(now=weekend), ctx, limits), "Market open").detail == "open (broker)"
    )
    closed = replace(EURUSD, market_open=False)
    decision = run(ctx=make_context(symbol=closed))
    assert_rejected(decision, "Market open", "market is closed (broker)")


def test_manual_ticket_volume_is_checked_not_computed() -> None:
    ctx = make_context(manual=True)
    signal = make_signal(bar_time=NOW - timedelta(hours=5))  # bar age irrelevant for manual
    ok = evaluate(signal, ctx, DEFAULT_LIMITS, requested_volume=D("0.20"))
    assert ok.approved and ok.volume == D("0.2") and ok.risk_amount == D("40.00")
    too_big = evaluate(signal, ctx, DEFAULT_LIMITS, requested_volume=D("0.30"))
    assert_rejected(too_big, "Position size", "the most you can trade is 0.25 lots")
    off_step = evaluate(signal, ctx, DEFAULT_LIMITS, requested_volume=D("0.105"))
    assert_rejected(off_step, "Position size", "multiple of 0.01")
    tiny = evaluate(signal, ctx, DEFAULT_LIMITS, requested_volume=D("0.001"))
    assert_rejected(tiny, "Position size", "outside the broker range")


def test_manual_ticket_still_needs_a_fresh_price() -> None:
    stale = quote("EURUSD", "1.10000", "1.10010", NOW - timedelta(minutes=10))
    ctx = make_context(manual=True, quote=stale, quote_lookup=lookup_from(stale))
    decision = evaluate(make_signal(), ctx, DEFAULT_LIMITS, requested_volume=D("0.1"))
    assert_rejected(decision, "Market data fresh", "price is 600s old")
