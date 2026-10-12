"""Contract specifications: how a strategy's BUY/SELL becomes something tradeable.

Strategies stay direction-based (BUY/SELL). The contract spec on an assignment
(or a backtest, or a manual ticket) decides what is bought:

    family      BUY          SELL         sized by
    SPOT        long         short        lots (risk % of equity, stop loss price)   Paper only
    RISE_FALL   CALL/CALLE   PUT/PUTE     a fixed stake (the most it can lose)
    MULTIPLIER  MULTUP       MULTDOWN     a fixed stake × multiplier

CALLE/PUTE ("allow equals") win when the exit spot EQUALS the entry spot;
plain CALL/PUT lose on a tie.

A Rise/Fall contract can lose at most its stake. A Multiplier contract is
closed by the broker ("stop out") before the loss exceeds the stake, so a
bounded stake satisfies the "every trade has a maximum loss" rule for both.

Durations follow Deriv's notation: `t` ticks, `s` seconds, `m` minutes,
`h` hours, `d` days. Broker limits arrive as strings such as "1t", "15s",
"1d" (`contracts_for` → min/max_contract_duration) and are parsed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fxrobot.domain.market import Side

CENT = Decimal("0.01")
MAX_STAKE = Decimal(100_000)

# Beginner default for candle-driven strategies: a 5-minute Rise/Fall. Tick
# contracts settle faster than one candle closes, so a signal computed on a
# closed bar could not be judged by the data that produced it.
DEFAULT_DURATION = 5
DEFAULT_DURATION_UNIT = "m"


class ContractFamily(StrEnum):
    RISE_FALL = "RISE_FALL"
    MULTIPLIER = "MULTIPLIER"
    SPOT = "SPOT"

    @property
    def is_contract(self) -> bool:
        """Stake-sized contract (as opposed to lots)."""
        return self is not ContractFamily.SPOT


class ContractType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"
    CALLE = "CALLE"
    PUTE = "PUTE"
    MULTUP = "MULTUP"
    MULTDOWN = "MULTDOWN"

    @property
    def side(self) -> Side:
        buys = (ContractType.CALL, ContractType.CALLE, ContractType.MULTUP)
        return Side.BUY if self in buys else Side.SELL

    @property
    def family(self) -> ContractFamily:
        if self in (ContractType.MULTUP, ContractType.MULTDOWN):
            return ContractFamily.MULTIPLIER
        return ContractFamily.RISE_FALL


class ContractOutcome(StrEnum):
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    SOLD = "SOLD"  # closed before expiry (or a multiplier closed by hand / TP / SL)
    CANCELLED = "CANCELLED"


UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
DURATION_UNITS = ("t", "s", "m", "h", "d")
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([tsmhd])\s*$")


def parse_duration(text: str) -> tuple[int, str] | None:
    """ "15s" → (15, "s"). None when malformed."""
    match = _DURATION_RE.match(str(text))
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


def duration_seconds(duration: int, unit: str) -> int | None:
    """Seconds for a time-based duration; None for ticks."""
    return None if unit == "t" else duration * UNIT_SECONDS[unit]


def contract_type_for(
    family: ContractFamily, side: Side, allow_equals: bool = False
) -> ContractType | None:
    """The broker contract that expresses a BUY/SELL signal (None for SPOT)."""
    if family is ContractFamily.RISE_FALL:
        if side is Side.BUY:
            return ContractType.CALLE if allow_equals else ContractType.CALL
        return ContractType.PUTE if allow_equals else ContractType.PUT
    if family is ContractFamily.MULTIPLIER:
        return ContractType.MULTUP if side is Side.BUY else ContractType.MULTDOWN
    return None


def rise_fall_won(contract_type: ContractType, entry: Decimal, exit_: Decimal) -> bool:
    """Settlement rule: CALL > , CALLE ≥ , PUT < , PUTE ≤ (equal spots lose CALL/PUT)."""
    if contract_type is ContractType.CALL:
        return exit_ > entry
    if contract_type is ContractType.CALLE:
        return exit_ >= entry
    if contract_type is ContractType.PUT:
        return exit_ < entry
    if contract_type is ContractType.PUTE:
        return exit_ <= entry
    raise ValueError(f"{contract_type} is not a Rise/Fall contract")


def multiplier_pnl(
    contract_type: ContractType, stake: Decimal, multiplier: int, entry: Decimal, price: Decimal
) -> Decimal:
    """stake × multiplier × (price ÷ entry − 1) × direction, floored at −stake (stop out)."""
    sign = 1 if contract_type is ContractType.MULTUP else -1
    raw = stake * multiplier * (price / entry - 1) * sign
    return max(raw, -stake)


def multiplier_limit_amounts(
    side: Side,
    stake: Decimal,
    multiplier: int,
    entry: Decimal,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Money amounts for a strategy's stop/target PRICES (amount = notional × |move| ÷ entry).

    A stop further away than the stake is dropped: the broker's stop out at a
    loss of the stake closes the contract first, so it would never trigger.
    """
    notional = stake * multiplier

    def amount(level: Decimal | None, losing: bool) -> Decimal | None:
        if level is None or entry <= 0:
            return None
        move = (level - entry) * side.sign
        if (move < 0) != losing or move == 0:
            return None  # wrong side of entry: not a usable level
        return (notional * abs(move) / entry).quantize(CENT, ROUND_HALF_UP)

    stop = amount(stop_loss, True)
    if stop is not None and stop >= stake:
        stop = None
    return stop, amount(take_profit, False)


class ContractSpec(BaseModel):
    """The contract settings of an assignment, backtest or manual ticket.

    Validated here (engine) and by Laravel (app/Support/ContractSpec.php) with
    the same rules. Broker-specific limits (allowed durations, multipliers,
    minimum stake) are checked separately against the broker's capabilities.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_family: ContractFamily = ContractFamily.SPOT
    duration: int | None = Field(default=None, ge=1, le=100_000)
    duration_unit: str | None = None
    allow_equals: bool = False
    stake: Decimal | None = Field(default=None, gt=0, le=MAX_STAKE, decimal_places=2)
    multiplier: int | None = Field(default=None, ge=1, le=5000)
    take_profit_amount: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    stop_loss_amount: Decimal | None = Field(default=None, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def _family_rules(self) -> ContractSpec:
        family = self.contract_family
        if family is ContractFamily.RISE_FALL:
            if self.duration is None or self.duration_unit is None:
                raise ValueError("Rise/Fall needs a duration and a duration unit")
            if self.duration_unit not in DURATION_UNITS:
                raise ValueError("duration_unit must be one of t, s, m, h, d")
            if (
                self.multiplier is not None
                or self.take_profit_amount is not None
                or self.stop_loss_amount is not None
            ):
                raise ValueError(
                    "Rise/Fall contracts have no multiplier, take profit or stop loss: "
                    "they settle at expiry"
                )
        elif family is ContractFamily.MULTIPLIER:
            if self.multiplier is None:
                raise ValueError("Multiplier contracts need a multiplier")
            if self.duration is not None or self.duration_unit is not None:
                raise ValueError("Multiplier contracts have no duration")
            if self.allow_equals:
                raise ValueError("allow_equals applies to Rise/Fall only")
            if (
                self.stake is not None
                and self.stop_loss_amount is not None
                and self.stop_loss_amount > self.stake
            ):
                raise ValueError("The stop-loss amount cannot exceed the stake")
        elif (
            any(
                v is not None
                for v in (
                    self.duration,
                    self.duration_unit,
                    self.stake,
                    self.multiplier,
                    self.take_profit_amount,
                    self.stop_loss_amount,
                )
            )
            or self.allow_equals
        ):
            raise ValueError("SPOT trades use lots and stop-loss prices, not contract settings")
        return self

    # ── helpers ──────────────────────────────────────────────────────────
    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> ContractSpec:
        """Validate a JSON object (None or {} = SPOT). Raises ValueError."""
        data = {k: v for k, v in (raw or {}).items() if v is not None and v != ""}
        try:
            if "stake" in data:
                data["stake"] = Decimal(str(data["stake"])).quantize(CENT)
            return cls.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ()))
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            raise ValueError(f"{where}: {message}" if where else message) from None
        except ArithmeticError:
            raise ValueError("stake must be a number") from None

    @classmethod
    def default_rise_fall(cls) -> ContractSpec:
        return cls(
            contract_family=ContractFamily.RISE_FALL,
            duration=DEFAULT_DURATION,
            duration_unit=DEFAULT_DURATION_UNIT,
        )

    @property
    def family(self) -> ContractFamily:
        return self.contract_family

    @property
    def seconds(self) -> int | None:
        if self.duration is None or self.duration_unit is None:
            return None
        return duration_seconds(self.duration, self.duration_unit)

    def contract_type(self, side: Side) -> ContractType | None:
        return contract_type_for(self.contract_family, side, self.allow_equals)

    def label(self) -> str:
        if self.contract_family is ContractFamily.RISE_FALL:
            return f"Rise/Fall {self.duration}{self.duration_unit}" + (
                " (equals win)" if self.allow_equals else ""
            )
        if self.contract_family is ContractFamily.MULTIPLIER:
            return f"Multiplier ×{self.multiplier}"
        return "Spot (lots)"

    def as_json(self) -> dict[str, Any]:
        return {
            "contract_family": self.contract_family.value,
            "duration": self.duration,
            "duration_unit": self.duration_unit,
            "allow_equals": self.allow_equals,
            "stake": None if self.stake is None else format(self.stake.quantize(CENT), "f"),
            "multiplier": self.multiplier,
            "take_profit_amount": _money(self.take_profit_amount),
            "stop_loss_amount": _money(self.stop_loss_amount),
        }


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(CENT), "f")


@dataclass(frozen=True)
class ContractOrder:
    """A concrete contract to buy: the spec resolved for one signal (type, stake)."""

    family: ContractFamily
    contract_type: ContractType
    stake: Decimal
    duration: int | None = None
    duration_unit: str | None = None
    multiplier: int | None = None
    take_profit_amount: Decimal | None = None
    stop_loss_amount: Decimal | None = None

    @classmethod
    def build(cls, spec: ContractSpec, side: Side, stake: Decimal) -> ContractOrder:
        ctype = spec.contract_type(side)
        if ctype is None:
            raise ValueError("SPOT trades are not contracts")
        return cls(
            family=spec.contract_family,
            contract_type=ctype,
            stake=stake.quantize(CENT),
            duration=spec.duration,
            duration_unit=spec.duration_unit,
            multiplier=spec.multiplier,
            take_profit_amount=spec.take_profit_amount,
            stop_loss_amount=spec.stop_loss_amount,
        )

    @property
    def seconds(self) -> int | None:
        if self.duration is None or self.duration_unit is None:
            return None
        return duration_seconds(self.duration, self.duration_unit)

    def expires_at(self, start: datetime) -> datetime | None:
        secs = self.seconds
        return None if secs is None else start + timedelta(seconds=secs)

    def as_spec(self) -> ContractSpec:
        return ContractSpec(
            contract_family=self.family,
            duration=self.duration,
            duration_unit=self.duration_unit,
            allow_equals=self.contract_type in (ContractType.CALLE, ContractType.PUTE),
            multiplier=self.multiplier,
            take_profit_amount=self.take_profit_amount,
            stop_loss_amount=self.stop_loss_amount,
        )


@dataclass(frozen=True)
class ContractFill:
    """What the broker reported for a bought contract (all money as Decimal)."""

    contract_id: str
    contract_type: ContractType
    buy_price: Decimal
    payout: Decimal | None = None
    transaction_id: str | None = None
    start_time: datetime | None = None
    expires_at: datetime | None = None
    longcode: str | None = None
    multiplier: int | None = None
    duration: int | None = None
    duration_unit: str | None = None
    entry_spot: Decimal | None = None
    commission: Decimal | None = None


# ── broker capabilities (contracts_for) ──────────────────────────────────


@dataclass(frozen=True)
class DurationRange:
    """One allowed duration window, e.g. ticks 1t–10t or time 15s–1d."""

    expiry_type: str | None
    minimum: str
    maximum: str

    def contains(self, duration: int, unit: str) -> bool:
        lo, hi = parse_duration(self.minimum), parse_duration(self.maximum)
        if lo is None or hi is None:
            return False
        if unit == "t" or lo[1] == "t" or hi[1] == "t":
            # ticks only compare with ticks
            return unit == "t" and lo[1] == "t" and hi[1] == "t" and lo[0] <= duration <= hi[0]
        secs = duration * UNIT_SECONDS[unit]
        return UNIT_SECONDS[lo[1]] * lo[0] <= secs <= UNIT_SECONDS[hi[1]] * hi[0]

    def as_json(self) -> dict[str, Any]:
        return {"expiry_type": self.expiry_type, "min": self.minimum, "max": self.maximum}


@dataclass(frozen=True)
class ContractCapabilities:
    """Which contracts a broker offers on one symbol (from `contracts_for`)."""

    symbol: str
    rise_fall: bool = False
    rise_fall_types: tuple[str, ...] = ()
    durations: tuple[DurationRange, ...] = ()
    multipliers: tuple[int, ...] = ()
    spot: bool = False
    market_open: bool | None = None
    trading_suspended: bool = False
    simulated: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allow_equals(self) -> bool:
        return "CALLE" in self.rise_fall_types and "PUTE" in self.rise_fall_types

    def check(self, spec: ContractSpec) -> str | None:
        """None when the spec can be traded here, otherwise a plain-English reason."""
        family = spec.contract_family
        if family is ContractFamily.SPOT:
            return (
                None
                if self.spot
                else (f"{self.symbol} is traded as contracts here: choose Rise/Fall or Multiplier.")
            )
        if family is ContractFamily.RISE_FALL:
            if not self.rise_fall:
                return f"Rise/Fall contracts are not offered on {self.symbol}."
            if spec.allow_equals and not self.allow_equals:
                return f"'Allow equals' (CALLE/PUTE) is not offered on {self.symbol}."
            if spec.duration is None or spec.duration_unit is None:
                return "Rise/Fall needs a duration."
            if not any(r.contains(spec.duration, spec.duration_unit) for r in self.durations):
                allowed = ", ".join(f"{r.minimum}–{r.maximum}" for r in self.durations) or "none"
                return (
                    f"A {spec.duration}{spec.duration_unit} Rise/Fall is not offered on "
                    f"{self.symbol} (allowed durations: {allowed})."
                )
            return None
        if not self.multipliers:
            return f"Multiplier contracts are not offered on {self.symbol}."
        if spec.multiplier not in self.multipliers:
            allowed = ", ".join(f"×{m}" for m in self.multipliers)
            return f"×{spec.multiplier} is not offered on {self.symbol} (allowed: {allowed})."
        return None

    def as_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "simulated": self.simulated,
            "market_open": self.market_open,
            "trading_suspended": self.trading_suspended,
            "families": {
                "RISE_FALL": {
                    "available": self.rise_fall,
                    "contract_types": list(self.rise_fall_types),
                    "allow_equals": self.allow_equals,
                    "durations": [r.as_json() for r in self.durations],
                },
                "MULTIPLIER": {
                    "available": bool(self.multipliers),
                    "contract_types": ["MULTUP", "MULTDOWN"] if self.multipliers else [],
                    "multipliers": list(self.multipliers),
                },
                "SPOT": {"available": self.spot},
            },
            "default_contract": (
                ContractSpec.default_rise_fall().as_json()
                if self.rise_fall
                else (
                    ContractSpec(
                        contract_family=ContractFamily.MULTIPLIER,
                        multiplier=self.multipliers[0],
                    ).as_json()
                    if self.multipliers
                    else ContractSpec().as_json()
                )
            ),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class StakeQuote:
    """A broker's price for a contract before buying (Deriv: a `proposal`).

    `stake_min` / `stake_max` come from `validation_params.stake`; None means
    the broker did not say, and the risk engine then fails closed.
    """

    stake_min: Decimal | None
    stake_max: Decimal | None
    ask_price: Decimal | None = None
    payout: Decimal | None = None
    simulated: bool = False
    detail: str = ""
    # Multipliers: the broker's range for limit_order amounts (Deriv:
    # validation_params.stop_loss / take_profit). None = not reported.
    stop_loss_min: Decimal | None = None
    stop_loss_max: Decimal | None = None
    take_profit_min: Decimal | None = None
    take_profit_max: Decimal | None = None
