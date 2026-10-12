"""The `rules` strategy: runs any user-built rule set (templates, builder, AI drafts).

Its parameters ARE the rule set. Like every strategy it only proposes a
BUY/SELL with a stop and a target; the contract spec of the assignment turns
that into a Rise/Fall, a Multiplier or a Spot trade, and the risk engine
decides whether it may trade at all.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

from pydantic import BaseModel

from fxrobot.domain.market import Side, Timeframe
from fxrobot.strategy_engine.base import (
    Check,
    Evaluation,
    ExitDecision,
    MarketView,
    Outcome,
    SignalIntent,
    Strategy,
)
from fxrobot.strategy_engine.rules.model import RuleSet, parse_rule_set
from fxrobot.strategy_engine.rules.series import ConditionResult, Frame, check, check_group

# Shown as the default when someone starts from a blank `rules` strategy.
EXAMPLE_RULES: dict[str, Any] = {
    "schema_version": 1,
    "timeframe": "M5",
    "entry": {
        "buy": {
            "all": [
                {
                    "left": {"indicator": "ema", "params": {"period": 20}},
                    "op": "crosses_above",
                    "right": {"indicator": "ema", "params": {"period": 50}},
                }
            ]
        },
        "sell": {
            "all": [
                {
                    "left": {"indicator": "ema", "params": {"period": 20}},
                    "op": "crosses_below",
                    "right": {"indicator": "ema", "params": {"period": 50}},
                }
            ]
        },
    },
}


def _check(prefix: str, r: ConditionResult) -> Check:
    return Check(f"{prefix}{r.text}", r.passed, r.detail)


class RulesStrategy(Strategy):
    key: ClassVar[str] = "rules"
    name: ClassVar[str] = "Rule-based strategy"
    code_version: ClassVar[str] = "1.0.0"
    description: ClassVar[str] = (
        "Runs a strategy built from rules (a template, the visual builder or a plain-English "
        "draft): WHEN the conditions hold on a closed bar THEN propose a buy or sell."
    )
    Params = RuleSet
    # Templates of this implementation are seeded by Laravel (database), not
    # registered from code defaults like the advanced built-ins.
    seeds_template: ClassVar[bool] = False

    def parse_params(self, raw: dict[str, Any]) -> BaseModel:
        return parse_rule_set(raw)

    def default_params(self) -> dict[str, Any]:
        return parse_rule_set(EXAMPLE_RULES).model_dump(mode="json")

    def timeframes(self, params: Any) -> tuple[Timeframe, ...]:
        rs: RuleSet = params
        return (rs.timeframe,)

    def required_bars(self, params: Any) -> dict[Timeframe, int]:
        rs: RuleSet = params
        return {rs.timeframe: rs.warmup_bars()}

    def has_exit_rules(self, params: Any) -> bool:
        rs: RuleSet = params
        return rs.has_exit_conditions()

    def _frame(self, view: MarketView, rs: RuleSet) -> tuple[Frame | None, Evaluation | None]:
        need = rs.warmup_bars()
        bars = list(view.candles(rs.timeframe)[-need:])
        if len(bars) < need:
            return None, Evaluation(
                Outcome.INSUFFICIENT_DATA,
                f"Need {need} closed {rs.timeframe} bars (have {len(bars)}).",
                bars[-1].time if bars else None,
            )
        return Frame(bars), None

    def evaluate(self, view: MarketView, params: Any) -> Evaluation:
        rs: RuleSet = params
        frame, early = self._frame(view, rs)
        if frame is None:
            assert early is not None  # noqa: S101
            return early
        bars = view.candles(rs.timeframe)
        bar_time = bars[-1].time
        digits = view.symbol.digits
        checks: list[Check] = []
        results: list[ConditionResult] = []

        filter_results = [check(frame, c, digits) for c in rs.filters]
        results += filter_results
        checks += [_check("Filter: ", r) for r in filter_results]
        filters_ok = all(r.passed for r in filter_results)

        matched: list[Side] = []
        for side, group in ((Side.BUY, rs.entry.buy), (Side.SELL, rs.entry.sell)):
            if group is None:
                continue
            passed, side_results = check_group(frame, group, digits)
            results += side_results
            mode = "" if group.mode == "all" or len(group.conditions) == 1 else " (any)"
            checks += [_check(f"{side.value}{mode}: ", r) for r in side_results]
            if passed:
                matched.append(side)

        if any(not r.available for r in results):
            return Evaluation(
                Outcome.INSUFFICIENT_DATA, "Indicators are still warming up.", bar_time, checks
            )
        if not filters_ok:
            failed = next(r for r in filter_results if not r.passed)
            return Evaluation(Outcome.NO_SETUP, f"Filter not met: {failed.text}.", bar_time, checks)
        if not matched:
            return Evaluation(
                Outcome.NO_SETUP, "No entry rule matched on this bar.", bar_time, checks
            )
        if len(matched) == 2:
            return Evaluation(
                Outcome.NO_SETUP,
                "The buy and the sell rules both matched — conflicting rules, no trade.",
                bar_time,
                checks,
            )
        side = matched[0]
        return self._signal(view, rs, frame, side, bar_time, checks)

    def _signal(
        self,
        view: MarketView,
        rs: RuleSet,
        frame: Frame,
        side: Side,
        bar_time: Any,
        checks: list[Check],
    ) -> Evaluation:
        s = side.sign
        digits = view.symbol.digits
        pip = float(view.symbol.pip_size)
        entry = float(frame.prices["close"][-1])
        stop_rule, target_rule = rs.exit.stop, rs.exit.target
        if stop_rule.type == "pips":
            distance = float(stop_rule.pips or 0) * pip
        else:
            distance = stop_rule.multiple * float(frame.atr(stop_rule.atr_period)[-1])
        if math.isnan(distance):  # ATR still warming up
            return Evaluation(Outcome.INSUFFICIENT_DATA, "ATR not available yet.", bar_time, checks)
        if distance <= 0:
            checks.append(Check("Valid stop", False, "the stop distance is zero"))
            return Evaluation(Outcome.NO_SETUP, "Invalid stop placement.", bar_time, checks)
        stop = entry - s * distance
        target: float | None = None
        if target_rule is not None:
            if target_rule.type == "rr":
                reward = target_rule.ratio * distance
            elif target_rule.type == "pips":
                reward = float(target_rule.pips or 0) * pip
            else:
                reward = target_rule.multiple * float(frame.atr(target_rule.atr_period)[-1])
            if not math.isnan(reward) and reward > 0:
                target = entry + s * reward
        quant = Decimal(1).scaleb(-digits)

        def dec(value: float) -> Decimal:
            return Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)

        if stop <= 0 or dec(stop) == dec(entry):
            checks.append(Check("Valid stop", False, "the stop is too close to the entry price"))
            return Evaluation(Outcome.NO_SETUP, "Invalid stop placement.", bar_time, checks)
        checks.append(
            Check(
                "Stop & target",
                True,
                f"stop {dec(stop)} ({stop_rule.to_text()})"
                + (f", target {dec(target)}" if target is not None else ", no target")
                + " — used by Spot and Multiplier trades ✓",
            )
        )
        reasons = [c.detail for c in checks if c.passed]
        signal = SignalIntent(
            side=side,
            timeframe=rs.timeframe,
            bar_time=bar_time,
            entry_price=dec(entry),
            stop_loss=dec(stop),
            take_profit=dec(target) if target is not None else None,
            reasons=reasons,
        )
        matched = rs.entry.buy if side is Side.BUY else rs.entry.sell
        summary = f"{side.value} signal: {matched.to_text() if matched else ''}."
        return Evaluation(Outcome.SIGNAL, summary[:300], bar_time, checks, signal)

    def evaluate_exit(self, view: MarketView, params: Any, side: Side) -> ExitDecision | None:
        rs: RuleSet = params
        group = rs.exit.close_buy_when if side is Side.BUY else rs.exit.close_sell_when
        if group is None:
            return None
        frame, early = self._frame(view, rs)
        if frame is None:
            return ExitDecision(False, early.summary if early else "Not enough data.")
        passed, results = check_group(frame, group, view.symbol.digits)
        checks = [_check(f"Exit {side.value}: ", r) for r in results]
        if passed:
            return ExitDecision(True, f"Exit rule met: {group.to_text()}.", checks)
        return ExitDecision(False, "Exit rule not met.", checks)
