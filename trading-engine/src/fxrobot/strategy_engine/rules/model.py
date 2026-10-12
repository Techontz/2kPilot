"""The declarative rule-set format (schema_version 1).

A rule set is DATA, never code: operands are price fields, numbers or
catalogued indicators; conditions compare two operands with a fixed list of
operators. Nothing in a rule set is executed or evaluated as an expression.

    {
      "schema_version": 1,
      "timeframe": "M5",
      "entry": {
        "buy":  {"all": [{"left": {"indicator": "ema", "params": {"period": 20}},
                          "op": "crosses_above",
                          "right": {"indicator": "ema", "params": {"period": 50}}}]},
        "sell": {"all": [ ... ]}
      },
      "filters": [ ... ],                      # all must hold before any entry
      "exit": {
        "stop":   {"type": "atr", "atr_period": 14, "multiple": 2.0},
        "target": {"type": "rr", "ratio": 2.0},
        "close_buy_when":  {"any": [ ... ]},    # optional early exits (Spot / Multiplier)
        "close_sell_when": null
      }
    }
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from fxrobot.domain.market import Timeframe
from fxrobot.strategy_engine.rules.catalog import (
    INDICATORS,
    MAX_CONDITIONS,
    MAX_CONSTANT,
    MAX_WITHIN_BARS,
    OPERATORS,
    PRICE_FIELDS,
    SCALE_LABELS,
    lookback,
)

PriceField = Literal["open", "high", "low", "close"]
IndicatorKey = Literal[
    "sma", "ema", "rsi", "macd", "bollinger", "atr", "highest", "lowest", "roc", "adx"
]
Operator = Literal["crosses_above", "crosses_below", "gt", "gte", "lt", "lte", "between"]
CROSSES = ("crosses_above", "crosses_below")


def fmt_number(value: float) -> str:
    """30.0 → "30", 0.25 → "0.25" (for text, never for calculations)."""
    return f"{value:g}" if abs(value) < 1e6 else f"{value:,.0f}"


class Operand(BaseModel):
    """Exactly one of: a price field, a number, or an indicator reference."""

    model_config = ConfigDict(extra="forbid")

    price: PriceField | None = None
    value: float | None = None
    indicator: IndicatorKey | None = None
    params: dict[str, int | float | str] = Field(default_factory=dict)
    output: str | None = None

    @field_validator("params", mode="before")
    @classmethod
    def _empty_params(cls, value: Any) -> Any:
        """Stored rule sets pass through PHP, which encodes an empty object as []."""
        return {} if value is None or value == [] else value

    @model_validator(mode="after")
    def _check(self) -> Operand:
        kinds = [k for k in ("price", "value", "indicator") if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError("Choose exactly one of a price, a number or an indicator")
        if self.indicator is None:
            if self.params or self.output is not None:
                raise ValueError("Only indicators have settings and outputs")
            if self.value is not None and (
                not math.isfinite(self.value) or abs(self.value) > MAX_CONSTANT
            ):
                raise ValueError(
                    f"Numbers must be between −{MAX_CONSTANT:,.0f} and {MAX_CONSTANT:,.0f}"
                )
            return self
        spec = INDICATORS[self.indicator]
        unknown = sorted(set(self.params) - {p.key for p in spec.params})
        if unknown:
            raise ValueError(f"{spec.short} has no setting called {', '.join(unknown)}")
        clean: dict[str, int | float | str] = {}
        for p in spec.params:
            raw = self.params.get(p.key, p.default)
            if p.kind == "source":
                if raw not in PRICE_FIELDS:
                    raise ValueError(f"{spec.short} price must be one of open, high, low, close")
                clean[p.key] = str(raw)
                continue
            if isinstance(raw, (str, bool)):
                raise ValueError(f"{spec.short} {p.label.lower()} must be a number")
            number = float(raw)
            if p.kind == "integer":
                if not number.is_integer():
                    raise ValueError(f"{spec.short} {p.label.lower()} must be a whole number")
                number = int(number)
            assert p.minimum is not None and p.maximum is not None  # noqa: S101
            if not p.minimum <= number <= p.maximum:
                raise ValueError(
                    f"{spec.short} {p.label.lower()} must be between "
                    f"{fmt_number(p.minimum)} and {fmt_number(p.maximum)}"
                )
            clean[p.key] = number
        if self.indicator == "macd" and int(clean["fast"]) >= int(clean["slow"]):
            raise ValueError(
                f"MACD fast period ({clean['fast']}) must be smaller than the slow period "
                f"({clean['slow']})"
            )
        output = self.output or spec.default_output
        if spec.output(output) is None:
            allowed = ", ".join(o.key for o in spec.outputs)
            raise ValueError(f"{spec.short} has no output {output!r} (choose: {allowed})")
        self.params, self.output = clean, output
        return self

    # ── descriptions ────────────────────────────────────────────────────
    @property
    def key(self) -> str:
        """Identity used to compute each series once per evaluation."""
        if self.price is not None:
            return f"price:{self.price}"
        if self.value is not None:
            return f"value:{self.value!r}"
        params = ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.indicator}({params}).{self.output}"

    @property
    def scale(self) -> str | None:
        """What the numbers mean; None for a plain number (comparable with anything)."""
        if self.value is not None:
            return None
        if self.price is not None or self.indicator is None:
            return "price"
        out = INDICATORS[self.indicator].output(self.output or "")
        return out.scale if out else None

    @property
    def is_constant(self) -> bool:
        return self.value is not None

    def lookback(self) -> int:
        return 1 if self.indicator is None else lookback(self.indicator, self.params)

    def label(self) -> str:
        if self.price is not None:
            return f"the {self.price}"
        if self.value is not None:
            return fmt_number(self.value)
        assert self.indicator is not None  # noqa: S101
        p = self.params
        if self.indicator in ("sma", "ema"):
            src = "" if p.get("source", "close") == "close" else f" of {p['source']}"
            return f"{self.indicator.upper()} {p['period']}{src}"
        if self.indicator in ("rsi", "atr", "roc"):
            return f"{self.indicator.upper()} {p['period']}"
        if self.indicator == "adx":
            di = {"adx": "ADX", "plus_di": "+DI", "minus_di": "−DI"}[self.output or "adx"]
            return f"{di} {p['period']}"
        if self.indicator == "macd":
            name = {
                "line": "MACD line",
                "signal": "MACD signal line",
                "histogram": "MACD histogram",
            }
            return f"{name[self.output or 'line']} ({p['fast']}, {p['slow']}, {p['signal']})"
        if self.indicator == "bollinger":
            band = {
                "upper": "the upper Bollinger band",
                "middle": "the middle Bollinger band",
                "lower": "the lower Bollinger band",
                "percent_b": "Bollinger %B",
            }[self.output or "upper"]
            return f"{band} ({p['period']}, {fmt_number(float(p['stddev']))})"
        word = "highest" if self.indicator == "highest" else "lowest"
        return f"the {word} {p['source']} of the previous {p['period']} bars"


class Condition(BaseModel):
    """left OP right, or left BETWEEN low AND high."""

    model_config = ConfigDict(extra="forbid")

    left: Operand
    op: Operator
    right: Operand | None = None
    low: Operand | None = None
    high: Operand | None = None
    within_bars: int | None = Field(default=None, ge=1, le=MAX_WITHIN_BARS)

    @model_validator(mode="after")
    def _check(self) -> Condition:
        if self.op == "between":
            if self.low is None or self.high is None or self.right is not None:
                raise ValueError("'is between' needs a low and a high value (and no other value)")
            others = [self.low, self.high]
        else:
            if self.right is None or self.low is not None or self.high is not None:
                raise ValueError(
                    f"'{OPERATORS[self.op]['label']}' needs exactly one value to compare with"
                )
            others = [self.right]
        if self.within_bars is not None and self.op not in CROSSES:
            raise ValueError("'within the last N bars' only applies to crosses above / below")
        if self.left.is_constant and all(o.is_constant for o in others):
            raise ValueError("A condition must look at the market, not only at fixed numbers")
        if self.left.is_constant and self.op in CROSSES:
            raise ValueError("A fixed number cannot cross anything: put it on the right-hand side")
        for other in others:
            if other.key == self.left.key:
                raise ValueError(f"{self.left.label()} is compared with itself")
            a, b = self.left.scale, other.scale
            if a is not None and b is not None and a != b:
                raise ValueError(
                    f"{self.left.label()} ({SCALE_LABELS[a]}) cannot be compared with "
                    f"{other.label()} ({SCALE_LABELS[b]})"
                )
        if (
            self.op == "between"
            and self.low is not None
            and self.high is not None
            and self.low.value is not None
            and self.high.value is not None
            and self.low.value > self.high.value
        ):
            raise ValueError("The low value of 'is between' must not be above the high value")
        return self

    def operands(self) -> list[Operand]:
        return [o for o in (self.left, self.right, self.low, self.high) if o is not None]

    def to_text(self) -> str:
        if self.op == "between":
            assert self.low is not None and self.high is not None  # noqa: S101
            return f"{self.left.label()} is between {self.low.label()} and {self.high.label()}"
        assert self.right is not None  # noqa: S101
        text = f"{self.left.label()} {OPERATORS[self.op]['label']} {self.right.label()}"
        if self.within_bars is not None and self.within_bars > 1:
            text += f" within the last {self.within_bars} bars"
        return text


class Group(BaseModel):
    """{"all": [...]} (every condition) or {"any": [...]} (at least one)."""

    model_config = ConfigDict(extra="forbid")

    all: list[Condition] | None = None
    any: list[Condition] | None = None

    @model_validator(mode="after")
    def _check(self) -> Group:
        if (self.all is None) == (self.any is None):
            raise ValueError("Use either 'all' or 'any' (exactly one)")
        if not self.conditions:
            raise ValueError("Add at least one condition")
        return self

    @property
    def mode(self) -> Literal["all", "any"]:
        return "all" if self.all is not None else "any"

    @property
    def conditions(self) -> list[Condition]:
        return list(self.all if self.all is not None else self.any or [])

    def to_text(self) -> str:
        parts = [c.to_text() for c in self.conditions]
        joiner = " and " if self.mode == "all" else " or "
        if len(parts) > 2:
            head = ", ".join(parts[:-1])
            return f"{head}{',' if self.mode == 'all' else ''}{joiner}{parts[-1]}"
        return joiner.join(parts)


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buy: Group | None = None
    sell: Group | None = None

    @model_validator(mode="after")
    def _check(self) -> Entry:
        if self.buy is None and self.sell is None:
            raise ValueError("Add a buy rule, a sell rule, or both")
        return self


class StopRule(BaseModel):
    """Protective stop for Spot trades (and Multiplier stop amounts)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["atr", "pips"] = "atr"
    atr_period: int = Field(default=14, ge=1, le=500)
    multiple: float = Field(default=2.0, ge=0.1, le=20)
    pips: float | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def _check(self) -> StopRule:
        if self.type == "pips" and self.pips is None:
            raise ValueError("A fixed-pip stop needs a number of pips")
        return self

    def to_text(self) -> str:
        if self.type == "pips":
            return f"{fmt_number(self.pips or 0)} pips"
        return f"{fmt_number(self.multiple)} × ATR {self.atr_period}"


class TargetRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rr", "atr", "pips"] = "rr"
    ratio: float = Field(default=2.0, ge=0.1, le=20)
    atr_period: int = Field(default=14, ge=1, le=500)
    multiple: float = Field(default=3.0, ge=0.1, le=50)
    pips: float | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def _check(self) -> TargetRule:
        if self.type == "pips" and self.pips is None:
            raise ValueError("A fixed-pip target needs a number of pips")
        return self

    def to_text(self) -> str:
        if self.type == "pips":
            return f"{fmt_number(self.pips or 0)} pips"
        if self.type == "atr":
            return f"{fmt_number(self.multiple)} × ATR {self.atr_period}"
        return f"{fmt_number(self.ratio)} × the stop distance"


class ExitRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop: StopRule = Field(default_factory=StopRule)
    target: TargetRule | None = Field(default_factory=TargetRule)
    close_buy_when: Group | None = None
    close_sell_when: Group | None = None


class RuleSet(BaseModel):
    """A complete strategy as data. Validated on every save, draft and run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    timeframe: Timeframe = Timeframe.M5
    entry: Entry
    filters: list[Condition] = Field(default_factory=list)
    exit: ExitRules = Field(default_factory=ExitRules)

    @model_validator(mode="after")
    def _check(self) -> RuleSet:
        total = len(self.all_conditions())
        if total > MAX_CONDITIONS:
            raise ValueError(
                f"A strategy can have at most {MAX_CONDITIONS} conditions in total (this one "
                f"has {total}) — simpler rules are easier to trust and less likely to be overfitted"
            )
        if self.exit.close_buy_when is not None and self.entry.buy is None:
            raise ValueError("There is an exit rule for buys, but no buy rule")
        if self.exit.close_sell_when is not None and self.entry.sell is None:
            raise ValueError("There is an exit rule for sells, but no sell rule")
        return self

    def all_conditions(self) -> list[Condition]:
        groups = [
            self.entry.buy,
            self.entry.sell,
            self.exit.close_buy_when,
            self.exit.close_sell_when,
        ]
        out = [c for g in groups if g is not None for c in g.conditions]
        return out + list(self.filters)

    def has_exit_conditions(self) -> bool:
        return self.exit.close_buy_when is not None or self.exit.close_sell_when is not None

    def warmup_bars(self) -> int:
        """Closed bars needed: the longest look-back, plus room to detect crosses."""
        longest = 1
        extra = 1
        for c in self.all_conditions():
            longest = max(longest, *(o.lookback() for o in c.operands()))
            if c.op in CROSSES:
                extra = max(extra, (c.within_bars or 1) + 1)
        atr_periods = [self.exit.stop.atr_period]
        if self.exit.target is not None and self.exit.target.type == "atr":
            atr_periods.append(self.exit.target.atr_period)
        longest = max(longest, *(3 * p + 1 for p in atr_periods))
        return longest + extra + 1

    def notes(self) -> list[str]:
        """Plain-English remarks shown next to a valid rule set."""
        out = []
        if self.has_exit_conditions():
            out.append(
                "Exit conditions close Spot and Multiplier trades early. Rise/Fall contracts "
                "always run until they expire, so exit conditions do not apply to them."
            )
        if self.exit.target is None:
            out.append(
                "There is no target: Spot trades are refused when the risk profile requires a "
                "minimum reward/risk."
            )
        out.append(
            "Stops and targets apply to Spot trades (and become money amounts for "
            "Multipliers). A Rise/Fall contract settles at expiry; its stake is the most it "
            "can lose."
        )
        return out

    def to_lines(self) -> list[str]:
        lines = []
        if self.entry.buy is not None:
            lines.append(f"Buy when {self.entry.buy.to_text()}.")
        if self.entry.sell is not None:
            lines.append(f"Sell when {self.entry.sell.to_text()}.")
        if self.filters:
            lines.append("Only trade when " + " and ".join(c.to_text() for c in self.filters) + ".")
        if self.exit.close_buy_when is not None:
            lines.append(f"Close a buy early when {self.exit.close_buy_when.to_text()}.")
        if self.exit.close_sell_when is not None:
            lines.append(f"Close a sell early when {self.exit.close_sell_when.to_text()}.")
        stop = f"Stop: {self.exit.stop.to_text()} from the entry"
        target = (
            f"; target: {self.exit.target.to_text()}"
            if self.exit.target is not None
            else "; no target"
        )
        lines.append(f"{stop}{target} (Spot and Multiplier trades).")
        lines.append(f"Checked on every closed {self.timeframe.value} bar.")
        return lines

    def to_text(self) -> str:
        """Human summary, e.g. "Buy when EMA 20 crosses above EMA 50 and RSI 14 is below 70." """
        return " ".join(self.to_lines())


# ── errors in plain English ──────────────────────────────────────────────


def _where(loc: tuple[Any, ...]) -> str:
    parts = list(loc)
    names = {
        "buy": "Buy rule",
        "sell": "Sell rule",
        "close_buy_when": "Exit rule for buys",
        "close_sell_when": "Exit rule for sells",
    }
    if (parts[:1] == ["entry"] and len(parts) > 1 and parts[1] in names) or (
        parts[:1] == ["exit"] and len(parts) > 1 and parts[1] in names
    ):
        head = names[str(parts[1])]
        rest = parts[2:]
    elif parts[:1] == ["exit"] and len(parts) > 1 and parts[1] in ("stop", "target"):
        return str(parts[1]).capitalize() + (
            f" ({'.'.join(str(p) for p in parts[2:])})" if len(parts) > 2 else ""
        )
    elif parts[:1] == ["filters"] and len(parts) > 1 and isinstance(parts[1], int):
        head, rest = f"Filter {parts[1] + 1}", parts[2:]
    else:
        return ".".join(str(p) for p in parts)
    if len(rest) >= 2 and rest[0] in ("all", "any") and isinstance(rest[1], int):
        head += f", condition {rest[1] + 1}"
        rest = rest[2:]
    side = [str(p) for p in rest if p in ("left", "right", "low", "high")]
    if side:
        head += f" ({side[0]} side)"
    return head


def problems(exc: ValidationError) -> list[str]:
    """Pydantic errors → short human messages, one per problem, de-duplicated."""
    out: list[str] = []
    for err in exc.errors():
        msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
        loc = tuple(p for p in err.get("loc", ()) if not str(p).startswith("function-"))
        where = _where(loc) if loc else ""
        text = f"{where}: {msg}" if where else msg
        if text not in out:
            out.append(text)
    return out


def parse_rule_set(raw: dict[str, Any]) -> RuleSet:
    """Validate a rule set. Raises RuleSetError with every problem listed."""
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RuleSetError(problems(exc)) from None


class RuleSetError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems) or "invalid rule set")
        self.problems = problems
