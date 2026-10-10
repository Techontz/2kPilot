"""Rule engine: indicators against hand-computed values, every operator, crossover
edge cases, validation messages, determinism, explanations, text summaries,
the builder catalogue and the built-in templates seeded by Laravel."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fxrobot.domain.market import Candle, Side, Timeframe
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries
from fxrobot.strategy_engine import Outcome, get_strategy
from fxrobot.strategy_engine.indicators import (
    bollinger,
    ema,
    highest,
    lowest,
    macd,
    roc,
    rsi,
    sma,
)
from fxrobot.strategy_engine.rules import RuleSet, RuleSetError, catalog_json, parse_rule_set
from fxrobot.strategy_engine.rules.model import Condition
from fxrobot.strategy_engine.rules.series import Frame, check
from fxrobot.strategy_engine.view import StaticView

SYMBOL = DEFAULT_SPECS["EURUSD"].symbol_info()
T0 = datetime(2025, 3, 3, tzinfo=UTC)
RULES = get_strategy("rules")
TEMPLATES = Path(__file__).resolve().parents[2] / "backend/database/data/strategy_templates.json"


def bars(
    closes: Sequence[float], tf: Timeframe = Timeframe.M5, wick: float = 0.0002
) -> list[Candle]:
    """Bar i closes at closes[i] and opens at the previous close."""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(
            Candle(
                T0 + i * tf.delta,
                Decimal(f"{o:.5f}"),
                Decimal(f"{max(o, c) + wick:.5f}"),
                Decimal(f"{min(o, c) - wick:.5f}"),
                Decimal(f"{c:.5f}"),
            )
        )
        prev = c
    return out


def cond(raw: dict[str, Any]) -> Condition:
    return Condition.model_validate(raw)


def price(field: str = "close") -> dict[str, Any]:
    return {"price": field}


def num(v: float) -> dict[str, Any]:
    return {"value": v}


def ind(name: str, output: str | None = None, **params: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"indicator": name, "params": params}
    if output:
        out["output"] = output
    return out


def rule_set(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "timeframe": "M5",
        "entry": {
            "buy": {
                "all": [{"left": price(), "op": "crosses_above", "right": ind("sma", period=3)}]
            }
        },
        "exit": {"stop": {"type": "pips", "pips": 10}, "target": {"type": "rr", "ratio": 2}},
    }
    base.update(overrides)
    return base


# ── indicators ───────────────────────────────────────────────────────────


def nan_equal(a: np.ndarray, b: Sequence[float]) -> bool:
    return bool(np.allclose(a, np.array(b, dtype=float), equal_nan=True, atol=1e-6))


def test_sma_and_roc() -> None:
    x = np.array([1.0, 2, 3, 4, 5])
    assert nan_equal(sma(x, 3), [math.nan, math.nan, 2, 3, 4])
    assert nan_equal(sma(x, 6), [math.nan] * 5)
    assert nan_equal(roc(np.array([100.0, 110, 121]), 1), [math.nan, 10, 10])


def test_rsi_wilder_by_hand() -> None:
    # changes +1, +1, −1, +2 (period 2): seed gain 1 / loss 0 → 100;
    # then gain 0.5 / loss 0.5 → 50; then gain 1.25 / loss 0.25 → RS 5 → 83.33.
    out = rsi(np.array([10.0, 11, 12, 11, 13]), 2)
    assert nan_equal(out, [math.nan, math.nan, 100, 50, 100 - 100 / 6])
    assert rsi(np.array([5.0] * 6), 2)[-1] == 50  # no movement at all
    assert rsi(np.arange(10.0, 0, -1), 3)[-1] == 0


def test_macd_lines() -> None:
    x = np.linspace(1.0, 2.0, 60)
    line, signal, hist = macd(x, 3, 6, 4)
    assert np.isnan(line[4]) and not np.isnan(line[5])  # slow EMA seeded at index 5
    assert np.isnan(signal[7]) and not np.isnan(signal[8])  # signal EMA of the line: 5 + 4 − 1
    np.testing.assert_allclose(hist[8:], (line - signal)[8:])
    np.testing.assert_allclose(line[5:], (ema(x, 3) - ema(x, 6))[5:])
    flat_line, _, flat_hist = macd(np.full(60, 1.5), 3, 6, 4)
    assert np.allclose(flat_line[5:], 0) and np.allclose(flat_hist[8:], 0)


def test_bollinger_by_hand() -> None:
    upper, middle, lower, pct_b = bollinger(np.array([1.0, 2, 3, 4, 5]), 5, 2)
    sd = math.sqrt(2)  # population standard deviation of 1..5
    assert middle[-1] == pytest.approx(3)
    assert upper[-1] == pytest.approx(3 + 2 * sd)
    assert lower[-1] == pytest.approx(3 - 2 * sd)
    assert pct_b[-1] == pytest.approx((5 - (3 - 2 * sd)) / (4 * sd))
    assert np.isnan(pct_b[3])
    _, _, _, flat = bollinger(np.full(5, 2.0), 5, 2)
    assert np.isnan(flat[-1])  # zero-width bands: %B undefined


def test_highest_lowest_exclude_the_current_bar() -> None:
    x = np.array([1.0, 3, 2, 5, 4])
    assert nan_equal(highest(x, 2), [math.nan, math.nan, 3, 3, 5])
    assert nan_equal(lowest(x, 2), [math.nan, math.nan, 1, 2, 2])


def test_indicators_have_no_look_ahead() -> None:
    x = np.random.default_rng(1).normal(1.1, 0.01, 200)
    y = x.copy()
    y[150:] *= 3
    for fn in (lambda v: sma(v, 20), lambda v: rsi(v, 14), lambda v: macd(v, 12, 26, 9)[2]):
        assert nan_equal(fn(x)[:150], list(fn(y)[:150]))
    for fn2 in (lambda v: bollinger(v, 20, 2)[3], lambda v: highest(v, 20), lambda v: roc(v, 5)):
        assert nan_equal(fn2(x)[:150], list(fn2(y)[:150]))


# ── operators ────────────────────────────────────────────────────────────


def run_check(closes: Sequence[float], raw: dict[str, Any]) -> tuple[bool, str, bool]:
    r = check(Frame(bars(closes)), cond(raw), SYMBOL.digits)
    return r.passed, r.detail, r.available


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("gt", 1.2, False),
        ("gt", 1.1, True),
        ("gte", 1.2, True),
        ("lt", 1.2, False),
        ("lt", 1.3, True),
        ("lte", 1.2, True),
    ],
)
def test_comparisons(op: str, value: float, expected: bool) -> None:
    passed, detail, _ = run_check([1.1, 1.2], {"left": price(), "op": op, "right": num(value)})
    assert passed is expected
    assert detail.endswith("✓" if expected else "✗")


def test_between_is_inclusive() -> None:
    raw = {"left": price(), "op": "between", "low": num(1.1), "high": num(1.2)}
    assert run_check([1.0, 1.2], raw)[0]
    assert run_check([1.0, 1.1], raw)[0]
    assert not run_check([1.0, 1.25], raw)[0]


def test_crosses_above_and_below() -> None:
    above = {"left": price(), "op": "crosses_above", "right": num(1.15)}
    below = {"left": price(), "op": "crosses_below", "right": num(1.15)}
    passed, detail, _ = run_check([1.1, 1.2], above)
    assert passed and "crossed above 1.15 ✓" in detail
    assert not run_check([1.2, 1.25], above)[0]  # already above: no new cross
    assert run_check([1.2, 1.1], below)[0]
    assert not run_check([1.1, 1.2], below)[0]


def test_crossover_edge_cases_with_equal_values() -> None:
    above = {"left": price(), "op": "crosses_above", "right": num(1.15)}
    assert run_check([1.15, 1.2], above)[0], "equal on the previous bar, above now = a cross"
    assert not run_check([1.1, 1.15], above)[0], "touching is not crossing"
    below = {"left": price(), "op": "crosses_below", "right": num(1.15)}
    assert run_check([1.15, 1.1], below)[0]


def test_cross_within_last_n_bars() -> None:
    raw = {"left": price(), "op": "crosses_above", "right": num(1.15), "within_bars": 3}
    passed, detail, _ = run_check([1.1, 1.2, 1.21, 1.22], raw)
    assert passed and "2 bars ago" in detail
    assert not run_check([1.1, 1.2, 1.21, 1.22, 1.23], raw)[0]  # 3 bars ago is outside


def test_warm_up_nan_is_reported_as_not_available() -> None:
    raw = {"left": price(), "op": "gt", "right": ind("sma", period=10)}
    passed, detail, available = run_check([1.1, 1.2, 1.3], raw)
    assert not passed and not available and "not enough data" in detail
    cross = {"left": ind("ema", period=2), "op": "crosses_above", "right": ind("ema", period=3)}
    assert not run_check([1.0, 1.1, 1.2], cross)[2]  # EMA 3 has one value: no cross yet


def test_explanations_show_values() -> None:
    raw = {"left": ind("rsi", period=2), "op": "lt", "right": num(30)}
    passed, detail, _ = run_check([1.0, 1.1, 1.2, 1.3], raw)
    assert not passed
    assert detail == "RSI 2 is 100.0 — needs to be below 30 ✗"


# ── validation ───────────────────────────────────────────────────────────


def problems_of(raw: dict[str, Any]) -> list[str]:
    with pytest.raises(RuleSetError) as exc:
        parse_rule_set(raw)
    return exc.value.problems


def test_valid_rule_set_is_normalised_with_defaults() -> None:
    rs = parse_rule_set(rule_set())
    left = rs.entry.buy.conditions[0].right  # type: ignore[union-attr]
    assert left is not None and left.params == {"period": 3, "source": "close"}
    assert left.output == "value"
    assert rs.schema_version == 1 and rs.exit.target is not None


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        (
            {"left": ind("macd", fast=26, slow=12), "op": "gt", "right": num(0)},
            "MACD fast period (26) must be smaller than the slow period (12)",
        ),
        (
            {"left": ind("rsi", period=14), "op": "crosses_above", "right": ind("ema", period=50)},
            "cannot be compared with EMA 50",
        ),
        (
            {"left": ind("ema", period=20), "op": "gt", "right": ind("ema", period=20)},
            "compared with itself",
        ),
        (
            {"left": num(30), "op": "crosses_above", "right": ind("rsi")},
            "A fixed number cannot cross",
        ),
        ({"left": num(1), "op": "gt", "right": num(2)}, "must look at the market"),
        (
            {"left": price(), "op": "gt", "right": num(1), "within_bars": 3},
            "only applies to crosses",
        ),
        (
            {"left": ind("ema", period=0), "op": "gt", "right": price()},
            "EMA period must be between 1 and 500",
        ),
        ({"left": ind("ema", period=2.5), "op": "gt", "right": price()}, "whole number"),
        (
            {"left": ind("ema", length=5), "op": "gt", "right": price()},
            "EMA has no setting called length",
        ),
        (
            {"left": ind("bollinger", output="width"), "op": "gt", "right": price()},
            "no output 'width'",
        ),
        ({"left": price(), "op": "between", "right": num(1)}, "needs a low and a high"),
        ({"left": price(), "op": "gt"}, "needs exactly one value"),
        ({"left": {"price": "close", "value": 1}, "op": "gt", "right": num(1)}, "exactly one of"),
    ],
)
def test_validation_messages_are_human(condition: dict[str, Any], message: str) -> None:
    problems = problems_of(rule_set(entry={"buy": {"all": [condition]}}))
    assert any(message in p for p in problems), problems
    assert all(p.startswith("Buy rule, condition 1") for p in problems), problems


def test_structural_validation() -> None:
    assert any("buy rule, a sell rule" in p for p in problems_of(rule_set(entry={})))
    assert any("either 'all' or 'any'" in p for p in problems_of(rule_set(entry={"buy": {}})))
    assert any(
        "at least one condition" in p for p in problems_of(rule_set(entry={"buy": {"all": []}}))
    )
    many = [{"left": price(), "op": "gt", "right": num(i)} for i in range(13)]
    assert any(
        "at most 12 conditions" in p for p in problems_of(rule_set(entry={"buy": {"all": many}}))
    )
    no_sell_exit = rule_set(
        exit={"close_sell_when": {"any": [{"left": price(), "op": "gt", "right": num(1)}]}}
    )
    assert any("no sell rule" in p for p in problems_of(no_sell_exit))
    assert any("Stop" in p for p in problems_of(rule_set(exit={"stop": {"type": "pips"}})))
    assert problems_of(rule_set(timeframe="M2"))
    assert problems_of(rule_set(schema_version=2))
    assert problems_of({**rule_set(), "code": "import os"})  # unknown keys are refused


def test_warmup_covers_the_longest_lookback() -> None:
    rs = parse_rule_set(
        rule_set(
            entry={
                "buy": {"all": [{"left": price(), "op": "gt", "right": ind("sma", period=200)}]}
            },
        )
    )
    assert rs.warmup_bars() >= 200
    macd_rs = parse_rule_set(
        rule_set(
            entry={
                "buy": {
                    "all": [
                        {"left": ind("macd"), "op": "crosses_above", "right": ind("macd", "signal")}
                    ]
                }
            }
        )
    )
    assert macd_rs.warmup_bars() >= 3 * 26 + 9


# ── text ─────────────────────────────────────────────────────────────────


def test_to_text_summary() -> None:
    rs = parse_rule_set(
        {
            "timeframe": "M5",
            "entry": {
                "buy": {
                    "all": [
                        {
                            "left": ind("ema", period=20),
                            "op": "crosses_above",
                            "right": ind("ema", period=50),
                        },
                        {"left": ind("rsi", period=14), "op": "lt", "right": num(70)},
                    ]
                },
                "sell": {"any": [{"left": ind("rsi", period=14), "op": "gt", "right": num(80)}]},
            },
            "filters": [{"left": price(), "op": "gt", "right": ind("sma", period=200)}],
        }
    )
    text = rs.to_text()
    assert text.startswith(
        "Buy when EMA 20 crosses above EMA 50 and RSI 14 is below 70. Sell when RSI 14 is above 80."
    )
    assert "Only trade when the close is above SMA 200." in text
    assert "Checked on every closed M5 bar." in text


# ── the strategy ─────────────────────────────────────────────────────────


def view(closes: Sequence[float], tf: Timeframe = Timeframe.M5) -> StaticView:
    return StaticView(SYMBOL, {tf: bars(closes, tf)})


def flat_then(last: Sequence[float], n: int = 60) -> list[float]:
    return [1.1] * n + list(last)


def test_signal_with_stop_and_target() -> None:
    params = RULES.parse_params(rule_set())
    ev = RULES.evaluate(view(flat_then([1.09, 1.08, 1.12])), params)
    assert ev.outcome is Outcome.SIGNAL and ev.signal is not None
    s = ev.signal
    assert s.side is Side.BUY
    assert s.entry_price == Decimal("1.12000")
    assert s.stop_loss == Decimal("1.11900")  # 10 pips
    assert s.take_profit == Decimal("1.12200")  # 2R
    assert s.timeframe is Timeframe.M5
    assert any("crossed above" in c.detail and c.passed for c in ev.checks)
    assert s.reasons


def test_atr_stop_and_no_setup_and_insufficient_data() -> None:
    params = RULES.parse_params(
        rule_set(exit={"stop": {"type": "atr", "atr_period": 5, "multiple": 2}})
    )
    ev = RULES.evaluate(view(flat_then([1.09, 1.08, 1.12])), params)
    assert ev.signal is not None and ev.signal.stop_loss is not None
    assert ev.signal.stop_loss < ev.signal.entry_price
    quiet = RULES.evaluate(view(flat_then([1.1, 1.1])), params)
    assert (
        quiet.outcome is Outcome.NO_SETUP and quiet.summary == "No entry rule matched on this bar."
    )
    short = RULES.evaluate(view([1.1, 1.2]), params)
    assert short.outcome is Outcome.INSUFFICIENT_DATA and "closed M5 bars" in short.summary


def test_filters_block_entries() -> None:
    raw = rule_set(filters=[{"left": price(), "op": "lt", "right": num(1.0)}])
    ev = RULES.evaluate(view(flat_then([1.09, 1.08, 1.12])), RULES.parse_params(raw))
    assert ev.outcome is Outcome.NO_SETUP and ev.summary.startswith("Filter not met")
    assert any(c.name.startswith("Filter:") and not c.passed for c in ev.checks)


def test_conflicting_buy_and_sell_never_trade() -> None:
    raw = rule_set(
        entry={
            "buy": {"all": [{"left": price(), "op": "gt", "right": num(1)}]},
            "sell": {"all": [{"left": price(), "op": "gt", "right": num(1)}]},
        }
    )
    ev = RULES.evaluate(view(flat_then([1.1])), RULES.parse_params(raw))
    assert ev.outcome is Outcome.NO_SETUP and "conflicting" in ev.summary


def test_any_group_and_sell_side() -> None:
    raw = rule_set(
        entry={
            "sell": {
                "any": [
                    {"left": price(), "op": "lt", "right": num(1.0)},
                    {"left": price(), "op": "crosses_below", "right": ind("sma", period=3)},
                ]
            }
        }
    )
    ev = RULES.evaluate(view(flat_then([1.11, 1.12, 1.08])), RULES.parse_params(raw))
    assert ev.signal is not None and ev.signal.side is Side.SELL
    assert ev.signal.stop_loss is not None and ev.signal.stop_loss > ev.signal.entry_price
    assert any(c.name.startswith("SELL (any)") and not c.passed for c in ev.checks)


def test_exit_rules() -> None:
    raw = rule_set(
        exit={
            "stop": {"type": "pips", "pips": 10},
            "close_buy_when": {"any": [{"left": price(), "op": "lt", "right": num(1.0)}]},
        }
    )
    params = RULES.parse_params(raw)
    assert RULES.has_exit_rules(params)
    closing = RULES.evaluate_exit(view(flat_then([0.99])), params, Side.BUY)
    assert closing is not None and closing.close and closing.checks[0].passed
    keep = RULES.evaluate_exit(view(flat_then([1.05])), params, Side.BUY)
    assert keep is not None and not keep.close
    assert RULES.evaluate_exit(view(flat_then([0.99])), params, Side.SELL) is None
    assert not RULES.has_exit_rules(RULES.parse_params(rule_set()))


def test_fixed_window_makes_live_and_backtest_agree() -> None:
    """More (older) history must not change a decision: evaluation uses a fixed window."""
    series = SyntheticSeries(DEFAULT_SPECS["EURUSD"], 5, T0, Timeframe.M5).bars(
        T0, T0 + timedelta(days=6)
    )
    raw = rule_set(
        entry={
            "buy": {
                "all": [
                    {
                        "left": ind("ema", period=9),
                        "op": "crosses_above",
                        "right": ind("ema", period=21),
                    }
                ]
            },
            "sell": {
                "all": [
                    {
                        "left": ind("ema", period=9),
                        "op": "crosses_below",
                        "right": ind("ema", period=21),
                    }
                ]
            },
        },
        filters=[{"left": ind("rsi", period=14), "op": "between", "low": num(5), "high": num(95)}],
    )
    params = RULES.parse_params(raw)
    need = params.warmup_bars()  # type: ignore[attr-defined]
    for end in range(need + 50, len(series), 97):
        short = StaticView(SYMBOL, {Timeframe.M5: series[end - need : end]})
        long = StaticView(SYMBOL, {Timeframe.M5: series[:end]})
        a, b = RULES.evaluate(short, params), RULES.evaluate(long, params)
        assert (a.outcome, a.summary, a.checks_json()) == (b.outcome, b.summary, b.checks_json())
        assert RULES.evaluate(short, params).checks_json() == a.checks_json()  # deterministic


# ── catalogue & templates ────────────────────────────────────────────────


def test_catalog_lists_everything_the_builder_needs() -> None:
    cat = catalog_json(ai_drafting_available=False)
    keys = {i["key"] for i in cat["indicators"]}
    assert keys == {"sma", "ema", "rsi", "macd", "bollinger", "atr", "highest", "lowest", "roc"}
    macd_spec = next(i for i in cat["indicators"] if i["key"] == "macd")
    assert [o["key"] for o in macd_spec["outputs"]] == ["line", "signal", "histogram"]
    assert {p["key"]: p["default"] for p in macd_spec["params"]} == {
        "fast": 12,
        "slow": 26,
        "signal": 9,
    }
    ops = {o["key"]: o["label"] for o in cat["operators"]}
    assert ops["crosses_above"] == "crosses above" and ops["between"] == "is between"
    assert cat["limits"]["max_conditions"] == 12 and cat["limits"]["max_period"] == 500
    assert cat["ai_drafting_available"] is False
    assert [f["key"] for f in cat["price_fields"]] == ["open", "high", "low", "close"]
    json.dumps(cat)  # serialisable


def test_rules_strategy_is_registered_and_json_schema_exists() -> None:
    assert RULES.key == "rules" and not RULES.seeds_template
    assert RULES.parse_params(RULES.default_params())
    assert RuleSet.model_json_schema()["title"] == "RuleSet"


def load_templates() -> list[dict[str, Any]]:
    if not TEMPLATES.exists():  # pragma: no cover - the monorepo always has it
        pytest.skip("backend/database/data/strategy_templates.json not found")
    data = json.loads(TEMPLATES.read_text())
    assert data["format"] == "tradepilot.strategy_templates"
    templates: list[dict[str, Any]] = data["templates"]
    return templates


def test_every_template_is_valid_and_its_text_matches_the_engine() -> None:
    templates = load_templates()
    assert {t["slug"] for t in templates} == {
        "ema-crossover",
        "rsi-mean-reversion",
        "ma-trend-filter",
        "bollinger-reversion",
        "macd-momentum",
        "breakout",
    }
    for t in templates:
        rs = parse_rule_set(t["rules"])
        assert rs.model_dump(mode="json") == t["rules"], f"{t['slug']} is not normalised"
        assert rs.to_text() == t["rules_text"], f"{t['slug']}: regenerate rules_text"
        d = t["details"]
        assert d["difficulty"] in ("beginner", "intermediate")
        assert d["suggested_timeframe"] == rs.timeframe.value
        assert d["how_it_works"] and d["struggles"] and "educational" in d["disclaimer"].lower()
        assert "R_75" in d["suggested_symbols"]
        assert d["suggested_contract"]["contract_family"] == "RISE_FALL"
        assert "profitable" not in t["summary"].lower()


def test_every_template_runs_on_synthetic_data() -> None:
    series = SyntheticSeries(DEFAULT_SPECS["EURUSD"], 7, T0, Timeframe.M5).bars(
        T0, T0 + timedelta(days=10)
    )
    m15 = SyntheticSeries(DEFAULT_SPECS["EURUSD"], 7, T0, Timeframe.M15).bars(
        T0, T0 + timedelta(days=20)
    )
    for t in load_templates():
        params = RULES.parse_params(t["rules"])
        tf = params.timeframe  # type: ignore[attr-defined]
        data = series if tf is Timeframe.M5 else m15
        outcomes = set()
        for end in range(params.warmup_bars(), len(data), 7):  # type: ignore[attr-defined]
            ev = RULES.evaluate(StaticView(SYMBOL, {tf: data[:end]}), params)
            outcomes.add(ev.outcome)
            assert ev.checks, t["slug"]
        assert Outcome.SIGNAL in outcomes, f"{t['slug']} never signals on synthetic data"


def test_empty_params_stored_by_php_are_accepted() -> None:
    """Laravel's array cast stores an empty JSON object as []; stored rule sets must still load."""
    rs = parse_rule_set(
        {
            "entry": {
                "buy": {
                    "all": [
                        {
                            "left": {"price": "close", "params": []},
                            "op": "gt",
                            "right": {"value": 1, "params": None},
                        }
                    ]
                }
            }
        }
    )
    assert rs.entry.buy is not None
    assert rs.entry.buy.conditions[0].left.params == {}
