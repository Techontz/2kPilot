"""Contract trading (Rise/Fall, Multipliers): the spec, stake-based risk rules,
the paper simulator, the contract-aware backtester and the engine pipeline."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.backtesting.engine import BacktestConfig, Backtester, BacktestError, BacktestResult
from fxrobot.broker_engine.adapters.paper import PaperBroker, PaperConfig
from fxrobot.broker_engine.errors import OrderRejectedError
from fxrobot.broker_engine.models import DealEntry, OrderRequest
from fxrobot.domain.contracts import (
    ContractCapabilities,
    ContractFamily,
    ContractOrder,
    ContractSpec,
    ContractType,
    DurationRange,
    StakeQuote,
    multiplier_limit_amounts,
    multiplier_pnl,
    parse_duration,
    rise_fall_won,
)
from fxrobot.domain.market import Candle, Side, Timeframe
from fxrobot.domain.trading import ExitReason, OrderType, TradeStatus
from fxrobot.models import Trade
from fxrobot.risk_engine.engine import OpenExposure, evaluate
from fxrobot.risk_engine.limits import RiskLimits
from tests import factories
from tests.conftest import SignedClient
from tests.paper_helpers import make_market
from tests.test_backtesting import (
    LOOSE,
    SYMBOL,
    ProbeStrategy,
    Script,
    W,
    flat_h1,
)
from tests.test_engine_pipeline import FAST_PARAMS, LOOSE_RISK, paper_broker, run_until
from tests.test_risk_engine import make_context, make_signal

D = Decimal


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProbeStrategy]:
    from fxrobot.strategy_engine import registry

    stub = ProbeStrategy()
    monkeypatch.setitem(registry._STRATEGIES, stub.key, stub)
    yield stub


RISE_FALL_5M = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=5, duration_unit="m")
QUOTE = StakeQuote(D("0.35"), D("50000"), payout=D("1.95"))


# ── the contract spec ────────────────────────────────────────────────────


def test_signals_map_to_contract_types() -> None:
    rf = ContractFamily.RISE_FALL
    assert RISE_FALL_5M.contract_type(Side.BUY) is ContractType.CALL
    assert RISE_FALL_5M.contract_type(Side.SELL) is ContractType.PUT
    equals = ContractSpec(contract_family=rf, duration=1, duration_unit="t", allow_equals=True)
    assert equals.contract_type(Side.BUY) is ContractType.CALLE
    assert equals.contract_type(Side.SELL) is ContractType.PUTE
    mult = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=100)
    assert mult.contract_type(Side.BUY) is ContractType.MULTUP
    assert mult.contract_type(Side.SELL) is ContractType.MULTDOWN
    assert ContractSpec().contract_type(Side.BUY) is None  # SPOT


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"contract_family": "RISE_FALL"}, "needs a duration"),
        ({"contract_family": "RISE_FALL", "duration": 5, "duration_unit": "w"}, "t, s, m, h, d"),
        (
            {"contract_family": "RISE_FALL", "duration": 5, "duration_unit": "m", "multiplier": 5},
            "settle at expiry",
        ),
        ({"contract_family": "MULTIPLIER"}, "need a multiplier"),
        ({"contract_family": "MULTIPLIER", "multiplier": 10, "duration": 5}, "no duration"),
        (
            {
                "contract_family": "MULTIPLIER",
                "multiplier": 10,
                "stake": "2",
                "stop_loss_amount": 3,
            },
            "cannot exceed the stake",
        ),
        ({"contract_family": "SPOT", "stake": "1"}, "lots"),
        ({"contract_family": "OPTIONS"}, "contract_family"),
        ({"contract_family": "RISE_FALL", "duration": 0, "duration_unit": "m"}, "duration"),
    ],
)
def test_invalid_specs_are_refused_with_a_reason(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ContractSpec.parse(raw)


def test_spec_round_trips_as_json() -> None:
    spec = ContractSpec.parse(
        {"contract_family": "RISE_FALL", "duration": "15", "duration_unit": "m", "stake": "2.5"}
    )
    assert spec.stake == D("2.50") and spec.seconds == 900
    assert ContractSpec.parse(spec.as_json()) == spec
    assert ContractSpec.parse(None) == ContractSpec()  # nothing = SPOT


def test_durations_are_parsed_and_compared_like_deriv() -> None:
    assert parse_duration("15s") == (15, "s") and parse_duration("1d") == (1, "d")
    assert parse_duration("5x") is None
    ticks = DurationRange("tick", "1t", "10t")
    intraday = DurationRange("intraday", "15s", "1d")
    assert ticks.contains(5, "t") and not ticks.contains(11, "t") and not ticks.contains(5, "s")
    assert intraday.contains(15, "s") and intraday.contains(1440, "m")
    assert not intraday.contains(14, "s") and not intraday.contains(25, "h")
    assert not intraday.contains(5, "t")


def test_settlement_rules_and_multiplier_arithmetic() -> None:
    assert rise_fall_won(ContractType.CALL, D(100), D("100.01"))
    assert not rise_fall_won(ContractType.CALL, D(100), D(100))  # ties lose CALL/PUT
    assert rise_fall_won(ContractType.CALLE, D(100), D(100))  # … and win CALLE/PUTE
    assert not rise_fall_won(ContractType.PUT, D(100), D(100))
    assert rise_fall_won(ContractType.PUTE, D(100), D(100))
    # stake 10 ×100: a 1 % rise doubles the stake; a 2 % fall cannot lose more than 10
    assert multiplier_pnl(ContractType.MULTUP, D(10), 100, D(100), D(101)) == D(10)
    assert multiplier_pnl(ContractType.MULTUP, D(10), 100, D(100), D(98)) == D(-10)
    assert multiplier_pnl(ContractType.MULTDOWN, D(10), 100, D(100), D("99.5")) == D(5)
    stop, take = multiplier_limit_amounts(Side.BUY, D(10), 100, D(100), D("99.5"), D(101))
    assert (stop, take) == (D("5.00"), D("10.00"))
    beyond, _ = multiplier_limit_amounts(Side.BUY, D(10), 100, D(100), D(98), None)
    assert beyond is None  # past the stop out: the broker closes it first


def test_capabilities_explain_unsupported_combinations() -> None:
    caps = ContractCapabilities(
        symbol="R_100",
        rise_fall=True,
        rise_fall_types=("CALL", "PUT"),
        durations=(DurationRange("intraday", "15s", "1d"),),
        multipliers=(40, 100),
    )
    assert caps.check(RISE_FALL_5M) is None
    equals = RISE_FALL_5M.model_copy(update={"allow_equals": True})
    assert "Allow equals" in (caps.check(equals) or "")
    assert "allowed durations: 15s–1d" in (
        caps.check(RISE_FALL_5M.model_copy(update={"duration": 2, "duration_unit": "d"})) or ""
    )
    mult = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=50)
    assert "allowed: ×40, ×100" in (caps.check(mult) or "")
    assert "choose Rise/Fall or Multiplier" in (caps.check(ContractSpec()) or "")


# ── stake-based risk rules ───────────────────────────────────────────────


def contract_ctx(**overrides: Any) -> Any:
    values: dict[str, Any] = {"contract": RISE_FALL_5M, "stake_quote": QUOTE}
    values.update(overrides)
    return make_context(**values)


def rule(decision: Any, name: str) -> Any:
    return next(c for c in decision.checks if c.rule == name)


def test_rise_fall_is_sized_by_the_stake() -> None:
    decision = evaluate(make_signal(stop_loss=None), contract_ctx(), RiskLimits())
    assert decision.approved, decision.rejection_reason
    assert decision.volume == 1 and decision.risk_amount == D("1.00")
    assert decision.contract is not None
    assert decision.contract.contract_type is ContractType.CALL
    assert decision.contract.stake == D("1.00") and decision.payout == D("1.95")
    assert "bounded" in rule(decision, "Stop loss required").detail
    assert "not applicable" in rule(decision, "Stop distance").detail
    assert "pays 1.95 USD" in rule(decision, "Stake").detail
    assert not any(c.rule in ("Position size", "Margin") for c in decision.checks)


def test_missing_broker_stake_limits_fail_closed() -> None:
    for quote in (None, StakeQuote(None, None, detail="no validation_params")):
        decision = evaluate(make_signal(), contract_ctx(stake_quote=quote), RiskLimits())
        assert not decision.approved
        assert "did not report its stake limits" in (decision.rejection_reason or "")


@pytest.mark.parametrize(
    ("limits", "ctx", "fragment"),
    [
        ({"stake_amount": "6", "max_stake_amount": None}, {}, "outside the broker"),
        ({"stake_amount": "2", "max_stake_amount": "1.5"}, {}, None),  # invalid profile
        ({}, {"contract": RISE_FALL_5M.model_copy(update={"stake": D(8)})}, "maximum stake"),
        ({}, {"stake_quote": StakeQuote(D(2), D(100))}, "outside the broker's stake range"),
        ({}, {"balance": D("0.50")}, "more than the balance"),
    ],
)
def test_stake_checks(limits: dict[str, Any], ctx: dict[str, Any], fragment: str | None) -> None:
    if fragment is None:
        with pytest.raises(ValueError, match="cannot exceed"):
            RiskLimits.from_mapping(limits)
        return
    quote = StakeQuote(D("0.35"), D(5)) if "stake_amount" in limits else QUOTE
    context = contract_ctx(**{"stake_quote": quote, **ctx})
    decision = evaluate(make_signal(), context, RiskLimits.from_mapping(limits))
    assert not decision.approved
    assert fragment in (decision.rejection_reason or "")


def test_explicit_stop_amount_cannot_exceed_the_stake() -> None:
    spec = ContractSpec(
        contract_family=ContractFamily.MULTIPLIER, multiplier=100, stop_loss_amount=D(3)
    )
    decision = evaluate(make_signal(), contract_ctx(contract=spec), RiskLimits())
    assert "larger than the stake" in (decision.rejection_reason or "")


def test_contract_problem_is_explained() -> None:
    decision = evaluate(
        make_signal(), contract_ctx(contract_problem="Rise/Fall is not offered"), RiskLimits()
    )
    assert decision.rejection_reason == "Contract supported: Rise/Fall is not offered"


def test_money_limits() -> None:
    limits = RiskLimits(max_daily_loss_amount=D(10), daily_profit_target_amount=D(5))
    reached = evaluate(make_signal(), contract_ctx(realized_pnl_today=D(-10)), limits)
    assert "lost 10.00 USD today" in (reached.rejection_reason or "")
    nearly = evaluate(make_signal(), contract_ctx(realized_pnl_today=D("-9.50")), limits)
    assert "losing this 1.00 USD stake would take" in (nearly.rejection_reason or "")
    target = evaluate(make_signal(), contract_ctx(realized_pnl_today=D("5.20")), limits)
    assert "target reached" in (target.rejection_reason or "")
    streak = evaluate(make_signal(), contract_ctx(consecutive_losses_today=3), RiskLimits())
    assert "3 losses in a row today" in (streak.rejection_reason or "")
    assert "until 00:00 UTC" in (streak.rejection_reason or "")
    # yesterday's streak does not count
    fresh = evaluate(make_signal(), contract_ctx(consecutive_losses=3), RiskLimits())
    assert fresh.approved, fresh.rejection_reason


def test_daily_loss_amount_counts_open_stakes_as_lost() -> None:
    """Worst case: every open contract loses its whole stake, then this one too."""
    limits = RiskLimits(max_daily_loss_amount=D(10), max_open_positions=None)

    def open_(*risks: str | None) -> list[OpenExposure]:
        return [
            OpenExposure("R_100", Side.BUY, D(1), D(r) if r is not None else None) for r in risks
        ]

    fits = contract_ctx(realized_pnl_today=D(-5), open_positions=open_("2", "2"))
    assert evaluate(make_signal(), fits, limits).approved  # 5 + 4 + 1 = 10: at the limit
    over = contract_ctx(realized_pnl_today=D(-5), open_positions=open_("2", "2", "2"))
    reason = evaluate(make_signal(), over, limits).rejection_reason or ""
    assert reason.startswith("Daily loss amount: ")
    assert "plus 6.00 USD in open contracts" in reason and "to 12.00 USD" in reason
    # Today's profit still offsets the open stakes.
    offset = contract_ctx(realized_pnl_today=D(3), open_positions=open_("2", "2", "2", "2", "2"))
    assert evaluate(make_signal(), offset, limits).approved  # 10 − 3 + 1 = 8
    unknown = contract_ctx(open_positions=open_(None))
    assert "risk of an open position is unknown" in (
        evaluate(make_signal(), unknown, limits).rejection_reason or ""
    )


def test_stake_above_the_per_trade_budget_is_refused_not_shrunk() -> None:
    limits = RiskLimits()  # the Beginner defaults: 0.5 % per trade, 1.00 stake

    def on(balance: Decimal, **kw: Any) -> Any:
        money = {"balance": balance, "equity": balance, "peak_equity": balance}
        return contract_ctx(**money, start_of_day_balance=balance, **kw)

    for balance in (D(10000), D(200)):  # a demo account; 0.5 % of 200 is exactly 1.00
        ok = evaluate(make_signal(), on(balance), limits)
        assert ok.approved, ok.rejection_reason
    small = evaluate(make_signal(), on(D(150)), limits)
    assert not small.approved and small.contract is None
    assert small.rejection_reason == (
        "Stake: 1.00 USD is above the 0.5% per-trade budget (0.75 USD of a 150.00 USD "
        "balance) — lower the stake or raise risk per trade"
    )
    multiplier = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=100)
    big = on(D(500), contract=multiplier.model_copy(update={"stake": D(5)}))
    assert "per-trade budget" in (evaluate(make_signal(), big, limits).rejection_reason or "")


def test_unsettled_trade_blocks_new_entries() -> None:
    decision = evaluate(make_signal(), contract_ctx(unsettled_trades=1), RiskLimits())
    assert (decision.rejection_reason or "").startswith(
        "Settled P/L: 1 closed trade(s) have no confirmed P/L yet"
    )


def test_spot_trades_also_obey_the_money_limits() -> None:
    limits = RiskLimits(max_daily_loss_amount=D(10))
    decision = evaluate(make_signal(), make_context(realized_pnl_today=D(-12)), limits)
    assert rule(decision, "Daily loss amount").passed is False


def test_suspended_symbol_is_not_tradable() -> None:
    from tests.test_risk_engine import EURUSD

    suspended = dataclasses.replace(EURUSD, trade_allowed=False, market_open=True)
    decision = evaluate(make_signal(), contract_ctx(symbol=suspended), RiskLimits())
    assert "suspended" in (decision.rejection_reason or "")


# ── paper contracts ──────────────────────────────────────────────────────


def paper(**config: Any) -> PaperBroker:
    broker = PaperBroker(
        make_market(("EURUSD", "R_100")), PaperConfig(commission_per_lot=D(0), **config)
    )
    broker.connect()
    return broker


def order(
    broker: PaperBroker, contract: ContractOrder, cid: str = "p" * 24, symbol: str = "R_100"
) -> Any:
    return broker.place_order(
        OrderRequest(
            cid,
            symbol,
            contract.contract_type.side,
            OrderType.MARKET,
            D(1),
            None,
            None,
            contract=contract,
        )
    )


def rf(minutes: int = 30, side: Side = Side.BUY, equals: bool = False) -> ContractOrder:
    spec = ContractSpec(
        contract_family=ContractFamily.RISE_FALL,
        duration=minutes,
        duration_unit="m",
        allow_equals=equals,
    )
    return ContractOrder.build(spec, side, D(10))


def test_paper_rise_fall_settles_at_expiry() -> None:
    broker = paper()
    result = order(broker, rf(30))
    fill = result.contract
    assert fill.payout == D("19.50") and fill.expires_at == broker.now() + timedelta(minutes=30)
    assert broker.get_account().balance == D("9990.00")
    position = broker.get_positions()[0]
    assert position.contract_type is ContractType.CALL and position.is_valid_to_sell is False
    with pytest.raises(OrderRejectedError, match="settles at expiry"):
        broker.close_position(result.broker_position_id, "q" * 24)
    broker.step(15)  # 15 one-minute bars: not yet expired
    assert broker.get_positions()
    broker.step(15)  # 30 minutes: settled on the close of that bar
    assert broker.get_positions() == []
    (out,) = [
        d
        for d in broker.get_deals(
            broker.now() - timedelta(days=1), broker.now() + timedelta(days=1)
        )
        if d.entry is DealEntry.OUT
    ]
    assert out.reason == "EXPIRY" and out.outcome in ("WON", "LOST")
    assert out.profit == (D("9.50") if out.outcome == "WON" else D("-10.00"))
    expected = D("10009.50") if out.outcome == "WON" else D("9990.00")
    assert broker.get_account().balance == expected


def test_paper_tick_contracts_count_simulated_bars() -> None:
    broker = paper()
    spec = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=3, duration_unit="t")
    order(broker, ContractOrder.build(spec, Side.SELL, D(5)))
    broker.step(2)
    assert broker.get_positions()
    broker.step(1)
    assert broker.get_positions() == []


def test_paper_refuses_durations_shorter_than_a_bar_and_lost_payout_is_configurable() -> None:
    broker = paper(rise_fall_payout_ratio=D("0.80"))
    too_short = ContractOrder.build(
        ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=30, duration_unit="s"),
        Side.BUY,
        D(10),
    )
    with pytest.raises(OrderRejectedError, match="not offered"):
        order(broker, too_short)  # the paper feed moves in 1-minute steps
    assert order(broker, rf(5)).contract.payout == D("18.00")


def test_paper_equal_prices_win_calle_and_lose_call(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = paper()
    call = order(broker, rf(1))
    calle = order(broker, rf(1, equals=True), cid="e" * 24)
    entry = broker.get_positions()[0].open_price
    flat = Candle(broker.now(), entry, entry, entry, entry)
    broker._process_bars([("R_100", flat)])  # type: ignore[attr-defined]
    deals = {
        d.position_id: d
        for d in broker.get_deals(
            broker.now() - timedelta(days=1), broker.now() + timedelta(days=1)
        )
        if d.entry is DealEntry.OUT
    }
    assert deals[call.broker_position_id].outcome == "LOST"
    assert deals[calle.broker_position_id].outcome == "WON"


def test_paper_multiplier_take_profit_stop_first_and_state_round_trip() -> None:
    broker = paper()
    spec = ContractSpec(
        contract_family=ContractFamily.MULTIPLIER,
        multiplier=10,
        take_profit_amount=D(2),
        stop_loss_amount=D(1),
    )
    result = order(broker, ContractOrder.build(spec, Side.BUY, D(10)))
    entry = result.fill_price
    state = broker.export_state()
    restored = PaperBroker(make_market(("EURUSD", "R_100")), PaperConfig(), state=state)
    assert restored.get_positions()[0].multiplier == 10
    # a bar reaching both levels: the stop is assumed first
    up, down = entry * D("1.03"), entry * D("0.98")
    broker._process_bars([("R_100", Candle(broker.now(), entry, up, down, up))])  # type: ignore[attr-defined]
    (out,) = [
        d
        for d in broker.get_deals(
            broker.now() - timedelta(days=1), broker.now() + timedelta(days=1)
        )
        if d.entry is DealEntry.OUT
    ]
    assert (out.reason, out.profit, out.outcome) == ("SL", D("-1.00"), "LOST")


def test_paper_multiplier_stop_acts_on_pnl_net_of_commission() -> None:
    """Deriv stops a Multiplier when its profit NET of commission reaches the stop."""
    broker = paper(multiplier_commission_pct=D("0.5"))  # 0.5 % of 10 × 10 = 0.50
    spec = ContractSpec(
        contract_family=ContractFamily.MULTIPLIER, multiplier=10, stop_loss_amount=D(1)
    )
    result = order(broker, ContractOrder.build(spec, Side.BUY, D(10)))
    entry = result.fill_price
    # The price move loses 0.60: with the 0.50 commission the contract is down 1.10.
    low = entry * D("0.994")
    broker._process_bars([("R_100", Candle(broker.now(), entry, entry, low, entry))])  # type: ignore[attr-defined]
    (out,) = [
        d
        for d in broker.get_deals(
            broker.now() - timedelta(days=1), broker.now() + timedelta(days=1)
        )
        if d.entry is DealEntry.OUT
    ]
    assert (out.reason, out.profit, out.outcome) == ("SL", D("-1.00"), "LOST")
    assert out.price == entry * (1 - D("0.5") / D(100))  # where the move lost stop − fee


# ── contract backtests ───────────────────────────────────────────────────


def bt(
    bars: list[Candle],
    contract: ContractSpec,
    limits: RiskLimits = LOOSE,
    **cfg: Any,
) -> BacktestResult:
    config = BacktestConfig(
        strategy_key="probe",
        params={},
        symbol=SYMBOL,
        start=W,
        end=W + timedelta(hours=len(bars)),
        initial_capital=D(1000),
        limits=limits,
        contract=contract,
        **cfg,
    )
    return Backtester(config, bars, Timeframe.H1).run()


BUY = Script(Side.BUY, D("1.09800"), D("1.10400"))
RF_2H = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=2, duration_unit="h")


def test_backtest_rise_fall_settles_after_duration(probe: ProbeStrategy) -> None:
    probe.script = {W + timedelta(hours=10): BUY}
    bars = flat_h1(
        overrides={
            10: ("1.10000", "1.10100", "1.09900", "1.10000"),
            11: ("1.10000", "1.10300", "1.09900", "1.10200"),
        }
    )
    result = bt(bars, RF_2H)
    (trade,) = result.trades
    assert trade.entry_price == D("1.10000")  # next bar's open, no spread for contracts
    assert trade.entry_time == W + timedelta(hours=10)
    assert trade.exit_time == W + timedelta(hours=12) and trade.exit_price == D("1.10200")
    assert (trade.outcome, trade.gross_pnl, trade.exit_reason) == (
        "WON",
        D("0.95"),
        ExitReason.EXPIRED,
    )
    assert trade.contract_type is ContractType.CALL and trade.stop_loss is None
    assert result.metrics["payout_ratio_is_estimate"] is True
    assert "3 % app markup" in " ".join(result.metrics["notes"])


def test_backtest_rise_fall_tie_loses_call(probe: ProbeStrategy) -> None:
    probe.script = {W + timedelta(hours=10): BUY}
    (trade,) = bt(flat_h1(), RF_2H, payout_ratio=D("0.8")).trades
    assert (trade.outcome, trade.net_pnl) == ("LOST", D("-1.00"))
    equals = RF_2H.model_copy(update={"allow_equals": True})
    probe.script = {W + timedelta(hours=10): BUY}
    (win,) = bt(flat_h1(), equals, payout_ratio=D("0.8")).trades
    assert (win.outcome, win.net_pnl) == ("WON", D("0.80"))


def test_backtest_refuses_durations_candles_cannot_resolve(probe: ProbeStrategy) -> None:
    with pytest.raises(BacktestError, match="ticks"):
        bt(flat_h1(), RF_2H.model_copy(update={"duration": 5, "duration_unit": "t"}))
    with pytest.raises(BacktestError, match="shorter than one H1 candle"):
        bt(flat_h1(), RF_2H.model_copy(update={"duration": 5, "duration_unit": "m"}))


def test_backtest_multiplier_tp_sl_and_stop_out(probe: ProbeStrategy) -> None:
    spec = ContractSpec(
        contract_family=ContractFamily.MULTIPLIER,
        multiplier=100,
        take_profit_amount=D("0.5"),
        stop_loss_amount=D("0.3"),
    )
    probe.script = {W + timedelta(hours=10): BUY}
    both = {
        10: ("1.10000", "1.10000", "1.10000", "1.10000"),
        11: ("1.10000", "1.11000", "1.09000", "1.10000"),
    }
    (trade,) = bt(flat_h1(overrides=both), spec, commission_pct=D("0.1")).trades
    # Like Deriv, the 0.30 stop acts on the P/L net of commission: the price move
    # loses 0.20, the commission 0.10.
    assert trade.exit_reason is ExitReason.STOP_LOSS and trade.gross_pnl == D("-0.20")
    assert trade.commission == D("0.10")  # 0.1 % of stake × multiplier (1 × 100)
    assert trade.net_pnl == D("-0.30")
    no_stop = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=100)
    probe.script = {W + timedelta(hours=10): Script(Side.BUY, D("1.05"), None)}
    crash = {11: ("1.10000", "1.10000", "1.00000", "1.00000")}
    (out,) = bt(flat_h1(overrides=crash), no_stop, commission_pct=D(1)).trades
    assert out.net_pnl == D("-1.00")  # never more than the stake


def test_backtest_applies_the_losing_streak_halt(probe: ProbeStrategy) -> None:
    probe.script = {W + timedelta(hours=h): BUY for h in range(2, 20, 3)}
    limits = dataclasses.replace(LOOSE, max_consecutive_losses=2)
    result = bt(flat_h1(), RF_2H, limits=limits)  # flat prices: every CALL loses
    assert len(result.trades) == 2
    assert result.rejections.get("Losing streak", 0) >= 1
    assert result.metrics["longest_losing_streak"] == 2
    assert result.metrics["win_rate"] == 0.0


# ── the engine pipeline on paper ─────────────────────────────────────────


def test_paper_assignment_trades_rise_fall_contracts(client: SignedClient, db: Session) -> None:
    account = factories.paper_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    version = factories.strategy_version(db, **FAST_PARAMS)
    factories.assignment(
        db,
        account,
        version,
        contract_family=ContractFamily.RISE_FALL,
        duration=15,
        duration_unit="m",
    )
    factories.resume_trading(db)

    def closed() -> bool:
        return (
            db.scalar(
                select(Trade).where(
                    Trade.account_id == account.id, Trade.status == TradeStatus.CLOSED
                )
            )
            is not None
        )

    run_until(client, str(account.connection_id), db, closed)
    trade = db.scalars(
        select(Trade).where(Trade.account_id == account.id, Trade.status == TradeStatus.CLOSED)
    ).first()
    assert trade is not None
    assert trade.contract_family is ContractFamily.RISE_FALL and trade.stake == D("1.00")
    assert trade.contract_type in (ContractType.CALL, ContractType.PUT)
    assert trade.exit_reason is ExitReason.EXPIRED and trade.outcome is not None
    assert trade.net_pnl in (D("0.95"), D("-1.00"))
    assert trade.risk_amount == D("1.00") and trade.volume == 1
    assert trade.exit_time is not None and trade.exit_time - trade.entry_time == timedelta(
        minutes=15
    )
    broker = paper_broker(client, str(account.connection_id))
    assert broker.capabilities.contract_families == ("SPOT", "RISE_FALL", "MULTIPLIER")
    assert uuid.UUID(str(trade.account_id)) == account.id


# ── contract backtests through the API ───────────────────────────────────


def test_rise_fall_backtest_via_api_on_a_synthetic_index(client: SignedClient, db: Session) -> None:
    from fxrobot.models import BacktestTrade
    from tests.test_backtesting import submit

    made = client.post(
        "/internal/datasets/synthetic",
        json={"symbol": "R_100", "timeframe": "H1", "days": 120, "seed": 3},
    )
    assert made.status_code == 200, made.text
    from fxrobot.models import Dataset

    row = db.get(Dataset, uuid.UUID(made.json()["id"]))
    assert row is not None and row.first_bar is not None and row.last_bar is not None
    ds = {
        "id": str(row.id),
        "first_bar": row.first_bar.isoformat(),
        "last_bar": row.last_bar.isoformat(),
    }
    contract = {"contract_family": "RISE_FALL", "duration": 2, "duration_unit": "h"}
    result = submit(client, ds, mode="single", contract=contract, payout_ratio="0.9")
    assert result["status"] == "COMPLETED", result["error"]
    assert result["config"]["contract"]["duration_unit"] == "h"
    assert result["config"]["payout_ratio_is_estimate"] is True
    assert result["metrics"]["payout_ratio"] == 0.9
    assert any("ESTIMATE" in w for w in result["warnings"])
    trades = list(
        db.scalars(
            select(BacktestTrade).where(BacktestTrade.backtest_id == uuid.UUID(result["id"]))
        )
    )
    assert trades and len(trades) == result["metrics"]["trades"]
    for t in trades:
        assert t.contract_type in ("CALL", "PUT") and t.stake == D("1.00")
        assert t.net_pnl in (D("0.90"), D("-1.00")) and t.stop_loss is None
        assert t.exit_time - t.entry_time == timedelta(hours=2)

    too_short = client.post(
        "/internal/backtests",
        json={
            "actor_id": str(factories.ensure_user(db)),
            "strategy_key": "trend_pullback",
            "initial_capital": "1000",
            "dataset_id": ds["id"],
            "start": ds["first_bar"],
            "end": ds["last_bar"],
            "contract": {"contract_family": "RISE_FALL", "duration": 5, "duration_unit": "t"},
        },
    )
    assert too_short.status_code == 422
    assert "do not show individual ticks" in too_short.json()["error"]["message"]
