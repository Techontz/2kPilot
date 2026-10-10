"""Event-driven backtester sharing strategy AND risk code with live trading.

Realism & bias controls (each covered by tests/test_backtesting.py):
* Decisions use CLOSED bars only (CursorView); higher timeframes are only
  visible once their period has ended.
* Entries fill at the NEXT base bar's open — never at the signal bar's close.
* Costs: spread (per-bar from data, or an override), adverse slippage on
  market entries and stop exits, commission per lot per side, optional swap.
* Intra-bar ambiguity: if a bar touches both stop and target, the STOP is
  assumed first. Gaps through a stop fill at the (worse) bar open.
* Position sizing and every risk rule come from the live risk engine.

Contracts (the assignment's contract spec, see fxrobot.domain.contracts):
* RISE_FALL — entry at the next bar's open; exit = close of the bar at entry +
  duration (the duration in bars of the data timeframe, rounded UP when it is
  not a whole number of bars). Durations shorter than one bar (ticks, seconds)
  are refused: candles cannot say where the price was in between. Won →
  +stake × payout_ratio, lost → −stake; equal prices lose CALL/PUT and win
  CALLE/PUTE. The payout ratio is an ESTIMATE: live payouts vary with every
  quote and include up to 3 % app markup.
* MULTIPLIER — P/L = stake × multiplier × (price ÷ entry − 1) × direction −
  commission (% of stake × multiplier), never below −stake (stop out).
  Take-profit / stop-loss money amounts close the trade intra-bar from the
  bar's high/low; the STOP is assumed first when both are touched.
* Stakes and the money limits (losing streak, daily loss amount, daily profit
  target, trades per day) go through the same risk engine as live trading.
  The backtest holds one contract at a time.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fxrobot.analytics import metrics
from fxrobot.domain.contracts import (
    ContractFamily,
    ContractSpec,
    ContractType,
    StakeQuote,
    multiplier_limit_amounts,
    multiplier_pnl,
    rise_fall_won,
)
from fxrobot.domain.market import Candle, Quote, Side, SymbolInfo, Timeframe
from fxrobot.domain.modes import AccountEnvironment, TradingMode
from fxrobot.domain.trading import ExitReason
from fxrobot.market_data.conversion import conversion_rate
from fxrobot.market_data.sessions import session_at
from fxrobot.risk_engine.engine import OpenExposure, RiskContext
from fxrobot.risk_engine.engine import evaluate as risk_evaluate
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.strategy_engine import Outcome, get_strategy
from fxrobot.strategy_engine.base import SignalIntent
from fxrobot.strategy_engine.view import CursorView

ROLLOVER_HOUR = 21  # swap charged when a position is held through 21:00 UTC


class BacktestError(ValueError):
    pass


@dataclass(frozen=True)
class CostModel:
    spread_pips: Decimal | None = None  # None → use per-bar spread from data (fallback 1.0)
    commission_per_lot: Decimal = Decimal("3.5")  # per side, account currency
    slippage_pips: Decimal = Decimal("0.2")  # adverse, market entries & stop exits
    swap_long_per_lot: Decimal = Decimal(0)  # per rollover, account currency
    swap_short_per_lot: Decimal = Decimal(0)
    default_spread_pips: Decimal = Decimal("1.0")

    def as_json(self) -> dict[str, str | None]:
        return {k: (None if v is None else str(v)) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class BacktestConfig:
    strategy_key: str
    params: dict[str, Any]
    symbol: SymbolInfo
    start: datetime
    end: datetime
    initial_capital: Decimal
    limits: RiskLimits
    costs: CostModel = field(default_factory=CostModel)
    account_currency: str = "USD"
    leverage: int = 100
    contract: ContractSpec = field(default_factory=ContractSpec)
    payout_ratio: Decimal = Decimal("0.95")  # Rise/Fall profit per 1 of stake (estimate)
    commission_pct: Decimal = Decimal(0)  # Multipliers: % of stake × multiplier
    stake_min: Decimal = Decimal("0.01")  # simulated broker stake range
    stake_max: Decimal = Decimal(100_000)


@dataclass
class SimTrade:
    side: Side
    signal_time: datetime
    entry_time: datetime
    entry_price: Decimal
    volume: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk_amount: Decimal
    reasons: list[str]
    session: str
    commission: Decimal = Decimal(0)
    swap: Decimal = Decimal(0)
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: ExitReason | None = None
    gross_pnl: Decimal = Decimal(0)
    # contracts
    contract_type: ContractType | None = None
    stake: Decimal | None = None
    payout: Decimal | None = None
    outcome: str | None = None
    bars_left: int | None = None  # Rise/Fall: bars until expiry
    multiplier: int | None = None
    take_amount: Decimal | None = None
    stop_amount: Decimal | None = None

    @property
    def costs(self) -> Decimal:
        return self.commission - self.swap  # swap is signed (+credit/−debit)

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.commission + self.swap

    @property
    def r_multiple(self) -> Decimal:
        return (
            (self.net_pnl / self.risk_amount).quantize(Decimal("0.01"))
            if self.risk_amount
            else Decimal(0)
        )


@dataclass
class BacktestResult:
    trades: list[SimTrade]
    metrics: dict[str, Any]
    signals: int
    rejections: dict[str, int]
    evaluations: int
    data_checksum: str = ""
    notes: list[str] = field(default_factory=list)


ProgressFn = Callable[[int], None]


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


class Backtester:
    def __init__(
        self, config: BacktestConfig, candles: Sequence[Candle], base_tf: Timeframe
    ) -> None:
        self.cfg = config
        self.base_tf = base_tf
        self.strategy = get_strategy(config.strategy_key)
        self.params = self.strategy.parse_params(config.params)
        self.entry_tf = self.strategy.timeframes(self.params)[0]
        # Early exits proposed by the strategy (rule sets with exit conditions).
        self.has_exits = self.strategy.has_exit_rules(self.params)
        self.pending_exit = False
        self.strategy_exits = 0
        if base_tf.seconds > self.entry_tf.seconds:
            raise BacktestError(
                f"Data timeframe {base_tf} is coarser than the strategy entry "
                f"timeframe {self.entry_tf}"
            )
        if (
            "USD" not in (config.symbol.base_currency, config.symbol.quote_currency)
            or config.account_currency != "USD"
        ):
            raise BacktestError(
                "Backtests currently support USD accounts on instruments quoted in USD only"
            )
        self.spec = config.contract
        self.expiry_bars: int | None = None
        self.notes: list[str] = []
        if self.spec.contract_family is ContractFamily.RISE_FALL:
            self.expiry_bars = expiry_bars(self.spec, base_tf)
            secs = self.spec.seconds or 0
            if secs % base_tf.seconds:
                self.notes.append(
                    f"The {self.spec.duration}{self.spec.duration_unit} duration is not a whole "
                    f"number of {base_tf} bars: contracts were settled at the close of bar "
                    f"{self.expiry_bars} after entry ({self.expiry_bars * base_tf.seconds // 60} "
                    "min)."
                )
        self.unsettled = 0
        self.candles = list(candles)
        if not self.candles:
            raise BacktestError("No candles in the selected range")
        self.view = CursorView(
            config.symbol, self.candles, base_tf, self.strategy.timeframes(self.params)
        )
        self.sym = config.symbol
        self.balance = config.initial_capital
        self.position: SimTrade | None = None
        self.pending: tuple[SignalIntent, Decimal, Decimal] | None = None  # signal, volume, risk
        self.closed: list[SimTrade] = []
        self.equity_points: list[tuple[datetime, Decimal]] = []
        self.peak_equity = config.initial_capital
        self.rejections: dict[str, int] = {}
        self.signals = 0
        self.evaluations = 0
        self._last_quote: Quote | None = None

    # ── prices & conversion ──────────────────────────────────────────────
    def _spread(self, bar: Candle) -> Decimal:
        if self.cfg.costs.spread_pips is not None:
            return self.cfg.costs.spread_pips * self.sym.pip_size
        if bar.spread_points is not None and bar.spread_points > 0:
            return Decimal(bar.spread_points) * self.sym.point
        return self.cfg.costs.default_spread_pips * self.sym.pip_size

    def _lookup(self, name: str) -> Quote | None:
        return self._last_quote if self._last_quote and name == self.sym.name else None

    def _to_account(self, amount_quote_ccy: Decimal) -> Decimal:
        rate = conversion_rate(self.sym.quote_currency, self.cfg.account_currency, self._lookup)
        if rate is None:
            raise BacktestError("cannot convert P/L to account currency")
        return amount_quote_ccy * rate

    def _pnl(self, trade: SimTrade, price: Decimal) -> Decimal:
        raw = (price - trade.entry_price) * trade.side.sign * trade.volume * self.sym.contract_size
        return self._to_account(raw)

    def _equity(self, bar: Candle) -> Decimal:
        if self.position is None:
            return self.balance
        if self.position.contract_type is not None:
            return self.balance + self._contract_mark(self.position, bar.close)
        spread = self._spread(bar)
        mark = bar.close if self.position.side is Side.BUY else bar.close + spread
        return (
            self.balance
            - self.position.commission
            + self.position.swap
            + self._pnl(self.position, mark)
        )

    # ── contracts ────────────────────────────────────────────────────────
    def _contract_mark(self, pos: SimTrade, price: Decimal) -> Decimal:
        """Unrealised P/L of an open contract (Rise/Fall is not marked: 0)."""
        if pos.contract_type is None or pos.multiplier is None or pos.stake is None:
            return Decimal(0)
        gross = multiplier_pnl(pos.contract_type, pos.stake, pos.multiplier, pos.entry_price, price)
        return max(gross - pos.commission, -pos.stake)

    def _open_contract(self, bar: Candle, signal: SignalIntent, stake: Decimal) -> None:
        spec = self.spec
        ctype = spec.contract_type(signal.side)
        if ctype is None:
            return
        entry = bar.open
        pos = SimTrade(
            side=signal.side,
            signal_time=signal.bar_time,
            entry_time=bar.time,
            entry_price=entry,
            volume=Decimal(1),
            stop_loss=None,
            take_profit=None,
            risk_amount=stake,
            reasons=signal.reasons,
            session=session_at(bar.time).value,
            contract_type=ctype,
            stake=stake,
        )
        if spec.contract_family is ContractFamily.RISE_FALL:
            pos.payout = _q2(stake * (1 + self.cfg.payout_ratio))
            pos.bars_left = self.expiry_bars
        else:
            mult = spec.multiplier or 1
            pos.multiplier = mult
            stop, take = spec.stop_loss_amount, spec.take_profit_amount
            if stop is None and take is None:  # the strategy's levels, as live trading does
                stop, take = multiplier_limit_amounts(
                    signal.side, stake, mult, entry, signal.stop_loss, signal.take_profit
                )
            pos.stop_amount, pos.take_amount = stop, take
            pos.stop_loss, pos.take_profit = signal.stop_loss, signal.take_profit
            pos.commission = _q2(stake * mult * self.cfg.commission_pct / 100)
        self.position = pos

    def _check_contract(self, bar: Candle) -> None:
        pos = self.position
        if pos is None or pos.contract_type is None or pos.stake is None:
            return
        if pos.bars_left is not None:  # Rise/Fall
            pos.bars_left -= 1
            if pos.bars_left > 0:
                return
            won = rise_fall_won(pos.contract_type, pos.entry_price, bar.close)
            gross = _q2(pos.stake * self.cfg.payout_ratio) if won else -pos.stake
            self._settle(pos, bar, bar.close, gross, "WON" if won else "LOST", ExitReason.EXPIRED)
            return
        mult = pos.multiplier or 1
        ctype = pos.contract_type

        def pnl(price: Decimal) -> Decimal:
            return multiplier_pnl(ctype, pos.stake or Decimal(0), mult, pos.entry_price, price)

        worst, best = (bar.low, bar.high) if pos.side is Side.BUY else (bar.high, bar.low)
        stop = min(pos.stop_amount, pos.stake) if pos.stop_amount is not None else pos.stake
        fee = pos.commission
        # Like Deriv, the stop loss / stop out acts on the profit NET of commission:
        # it triggers when the price move has lost (stop − commission).
        if pnl(bar.open) - fee <= -stop:  # gapped through the stop: the (worse) open
            self._settle(pos, bar, bar.open, pnl(bar.open), "LOST", ExitReason.STOP_LOSS)
        elif pnl(worst) - fee <= -stop:  # stop first when a bar touches both
            move = max(stop - fee, Decimal(0))
            price = pos.entry_price * (1 - Decimal(pos.side.sign) * move / (pos.stake * mult))
            self._settle(pos, bar, price, -move, "LOST", ExitReason.STOP_LOSS)
        elif pos.take_amount is not None and pnl(best) >= pos.take_amount:
            price = pos.entry_price * (
                1 + Decimal(pos.side.sign) * pos.take_amount / (pos.stake * mult)
            )
            self._settle(pos, bar, price, pos.take_amount, "WON", ExitReason.TAKE_PROFIT)

    def _settle(
        self,
        pos: SimTrade,
        bar: Candle,
        price: Decimal,
        gross: Decimal,
        outcome: str,
        reason: ExitReason,
    ) -> None:
        stake = pos.stake or Decimal(0)
        gross = _q2(gross)
        if gross - pos.commission < -stake:  # a contract never loses more than its stake
            gross = -stake + pos.commission
        pos.gross_pnl = gross
        pos.exit_price = price
        pos.exit_time = bar.time + self.base_tf.delta
        pos.exit_reason = reason
        pos.outcome = outcome
        self.balance += pos.net_pnl
        self.closed.append(pos)
        self.position = None

    # ── fills ────────────────────────────────────────────────────────────
    def _open(self, bar: Candle) -> None:
        if self.pending is None:
            return
        signal, volume, risk = self.pending
        self.pending = None
        if self.spec.contract_family.is_contract:
            self._open_contract(bar, signal, risk)
            return
        stop_loss = signal.stop_loss
        if stop_loss is None:
            return
        spread = self._spread(bar)
        slip = self.cfg.costs.slippage_pips * self.sym.pip_size
        price = bar.open + spread + slip if signal.side is Side.BUY else bar.open - slip
        # Re-validate stops against the actual fill (gap past the stop → skip trade).
        if (price - stop_loss) * signal.side.sign <= 0:
            self.rejections["Gap through stop before entry"] = (
                self.rejections.get("Gap through stop before entry", 0) + 1
            )
            return
        self.position = SimTrade(
            side=signal.side,
            signal_time=signal.bar_time,
            entry_time=bar.time,
            entry_price=price,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=signal.take_profit,
            risk_amount=risk,
            reasons=signal.reasons,
            session=session_at(bar.time).value,
            commission=_q2(self.cfg.costs.commission_per_lot * volume),
        )

    def _check_exit(self, bar: Candle) -> None:
        pos = self.position
        if pos is None:
            return
        if pos.contract_type is not None:
            self._check_contract(bar)
            return
        if pos.stop_loss is None:
            return
        spread = self._spread(bar)
        slip = self.cfg.costs.slippage_pips * self.sym.pip_size
        if pos.side is Side.BUY:
            o, hi, lo = bar.open, bar.high, bar.low
            if lo <= pos.stop_loss:
                self._close(min(o, pos.stop_loss) - slip, bar, ExitReason.STOP_LOSS)
            elif pos.take_profit is not None and hi >= pos.take_profit:
                self._close(max(o, pos.take_profit), bar, ExitReason.TAKE_PROFIT)
        else:
            o, hi, lo = bar.open + spread, bar.high + spread, bar.low + spread
            if hi >= pos.stop_loss:
                self._close(max(o, pos.stop_loss) + slip, bar, ExitReason.STOP_LOSS)
            elif pos.take_profit is not None and lo <= pos.take_profit:
                self._close(min(o, pos.take_profit), bar, ExitReason.TAKE_PROFIT)

    def _close(self, price: Decimal, bar: Candle, reason: ExitReason) -> None:
        pos = self.position
        if pos is None:
            return
        pos.exit_price, pos.exit_time, pos.exit_reason = (
            price,
            bar.time + self.base_tf.delta,
            reason,
        )
        pos.gross_pnl = _q2(self._pnl(pos, price))
        pos.commission = _q2(pos.commission + self.cfg.costs.commission_per_lot * pos.volume)
        self.balance += pos.net_pnl
        self.closed.append(pos)
        self.position = None

    def _swap(self, bar: Candle) -> None:
        if self.position is not None and self.position.contract_type is not None:
            return  # contracts have no overnight swap
        if self.position is not None and bar.time.hour == ROLLOVER_HOUR and bar.time.minute == 0:
            rate = (
                self.cfg.costs.swap_long_per_lot
                if self.position.side is Side.BUY
                else self.cfg.costs.swap_short_per_lot
            )
            self.position.swap += _q2(rate * self.position.volume)

    # ── risk context from simulation state ───────────────────────────────
    def _context(self, now: datetime, bar: Candle) -> RiskContext:
        spread = self._spread(bar)
        quote = Quote(self.sym.name, bar.close, bar.close + spread, now)
        self._last_quote = quote
        d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        w0 = d0 - timedelta(days=now.weekday())
        realized_today = sum(
            (t.net_pnl for t in self.closed if t.exit_time and t.exit_time >= d0), Decimal(0)
        )
        realized_week = sum(
            (t.net_pnl for t in self.closed if t.exit_time and t.exit_time >= w0), Decimal(0)
        )
        consecutive = 0
        for t in reversed(self.closed):
            if t.net_pnl < 0:
                consecutive += 1
            else:
                break
        consecutive_today = 0
        for t in reversed(self.closed):
            if t.exit_time is None or t.exit_time < d0 or t.net_pnl >= 0:
                break
            consecutive_today += 1
        equity = self._equity(bar)
        unrealized = equity - self.balance
        exposures = []
        if self.position is not None:
            exposures.append(
                OpenExposure(
                    self.sym.name,
                    self.position.side,
                    self.position.volume,
                    self.position.risk_amount,
                )
            )
        trades_today = sum(
            1
            for t in [*self.closed, *([self.position] if self.position else [])]
            if t.entry_time >= d0
        )
        return RiskContext(
            now=now,
            mode=TradingMode.DEMO,
            kill_switch_engaged=False,
            platform_halted=False,
            live_trading_locked=True,
            live_authorized=False,
            account_environment=AccountEnvironment.PAPER,
            account_trading_enabled=True,
            broker_connected=True,
            account_currency=self.cfg.account_currency,
            balance=self.balance,
            equity=equity,
            free_margin=equity,
            leverage=self.cfg.leverage,
            symbol=self.sym,
            quote=quote,
            quote_lookup=self._lookup,
            open_positions=exposures,
            realized_pnl_today=realized_today,
            realized_pnl_week=realized_week,
            unrealized_pnl=unrealized,
            start_of_day_balance=self.balance - realized_today,
            start_of_week_balance=self.balance - realized_week,
            peak_equity=self.peak_equity,
            trades_today=trades_today,
            consecutive_losses=consecutive,
            last_loss_at=self.closed[-1].exit_time if consecutive else None,
            contract=self.spec,
            consecutive_losses_today=consecutive_today,
            stake_quote=self._stake_quote(),
        )

    def _stake_quote(self) -> StakeQuote | None:
        if not self.spec.contract_family.is_contract:
            return None
        payout = None
        if self.spec.contract_family is ContractFamily.RISE_FALL:
            stake = self.spec.stake if self.spec.stake is not None else self.cfg.limits.stake_amount
            payout = _q2(stake * (1 + self.cfg.payout_ratio))
        return StakeQuote(self.cfg.stake_min, self.cfg.stake_max, payout=payout, simulated=True)

    # ── main loop ────────────────────────────────────────────────────────
    def run(self, progress: ProgressFn | None = None) -> BacktestResult:
        start, end = self.cfg.start, self.cfg.end
        total = len(self.candles)
        for i, bar in enumerate(self.candles):
            if bar.time >= end:
                break
            in_window = bar.time >= start
            if in_window and self.pending_exit:
                self._exit_at_open(bar)
            if in_window and self.pending is not None:
                self._open(bar)
            if in_window:
                self._check_exit(bar)
                self._swap(bar)
            close_time = bar.time + self.base_tf.delta
            equity = self._equity(bar)
            self.peak_equity = max(self.peak_equity, equity)
            if in_window and self.entry_tf.floor(close_time) == close_time:
                self.equity_points.append((close_time, equity))
                self._evaluate(close_time, bar)
            if progress and i % 500 == 0:
                progress(int(i / total * 100))
        last = next((c for c in reversed(self.candles) if c.time < end), self.candles[-1])
        if self.position is not None and self.position.bars_left is not None:
            self.unsettled += 1  # a Rise/Fall that had not expired when the data ended
            self.position = None
        if self.position is not None and self.position.contract_type is not None:
            pos = self.position
            mark = self._contract_mark(pos, last.close) + pos.commission
            self._settle(pos, last, last.close, mark, "SOLD", ExitReason.END_OF_TEST)
        if self.position is not None:
            spread = self._spread(last)
            price = last.close if self.position.side is Side.BUY else last.close + spread
            self._close(price, last, ExitReason.END_OF_TEST)
        self.pending = None
        if self.equity_points:
            self.equity_points.append((last.time + self.base_tf.delta, self.balance))
        stats = [
            metrics.TradeStat(
                net_pnl=t.net_pnl,
                entry_time=t.entry_time,
                exit_time=t.exit_time or t.entry_time,
                symbol=self.sym.name,
                side=t.side.value,
                session=t.session,
                r_multiple=t.r_multiple,
                costs=t.costs,
            )
            for t in self.closed
        ]
        result = metrics.compute(stats, self.cfg.initial_capital, self.equity_points)
        result["signals"] = self.signals
        if self.has_exits:
            result["strategy_exits"] = self.strategy_exits
        result["evaluations"] = self.evaluations
        result["rejections"] = dict(sorted(self.rejections.items(), key=lambda kv: -kv[1]))
        result["contract"] = self.spec.as_json()
        if self.unsettled:
            self.notes.append(
                f"{self.unsettled} Rise/Fall contract(s) had not expired when the data ended "
                "and are left out."
            )
        if self.spec.contract_family is ContractFamily.RISE_FALL:
            result["payout_ratio"] = float(self.cfg.payout_ratio)
            result["payout_ratio_is_estimate"] = True
            self.notes.append(
                f"Payouts are an ESTIMATE ({self.cfg.payout_ratio} × stake profit per win). "
                "Live Deriv payouts vary with every price quote and include up to 3 % app "
                "markup."
            )
        if self.spec.contract_family is ContractFamily.MULTIPLIER:
            result["commission_pct"] = float(self.cfg.commission_pct)
            result["commission_is_estimate"] = True
        result["outcomes"] = {
            k: sum(1 for t in self.closed if t.outcome == k)
            for k in ("WON", "LOST", "SOLD")
            if any(t.outcome == k for t in self.closed)
        }
        result["notes"] = list(self.notes)
        return BacktestResult(
            self.closed,
            result,
            self.signals,
            self.rejections,
            self.evaluations,
            notes=list(self.notes),
        )

    def _exit_at_open(self, bar: Candle) -> None:
        """Close at this bar's open: the strategy's exit rule fired on the previous close."""
        self.pending_exit = False
        pos = self.position
        if pos is None:
            return
        self.strategy_exits += 1
        if pos.contract_type is not None:
            if pos.bars_left is not None:
                return  # Rise/Fall: never closed early
            gross = multiplier_pnl(
                pos.contract_type,
                pos.stake or Decimal(0),
                pos.multiplier or 1,
                pos.entry_price,
                bar.open,
            )
            self._settle(pos, bar, bar.open, gross, "SOLD", ExitReason.STRATEGY)
            return
        slip = self.cfg.costs.slippage_pips * self.sym.pip_size
        # A buy is sold at the bid (bar prices); a sell is bought back at the ask.
        spread = Decimal(0) if pos.side is Side.BUY else self._spread(bar)
        self._close(bar.open + spread - slip * pos.side.sign, bar, ExitReason.STRATEGY)

    def _evaluate(self, now: datetime, bar: Candle) -> None:
        self.view.set_time(now)
        pos = self.position
        if (
            self.has_exits
            and pos is not None
            and pos.bars_left is None  # not a Rise/Fall
            and not self.pending_exit
        ):
            exit_decision = self.strategy.evaluate_exit(self.view, self.params, pos.side)
            if exit_decision is not None and exit_decision.close:
                self.pending_exit = True  # filled at the next bar's open, like entries
        evaluation = self.strategy.evaluate(self.view, self.params)
        self.evaluations += 1
        if evaluation.outcome is not Outcome.SIGNAL or evaluation.signal is None:
            return
        self.signals += 1
        if self.pending is not None:
            return
        if self.spec.contract_family.is_contract and self.position is not None:
            key = "One contract at a time (backtest)"
            self.rejections[key] = self.rejections.get(key, 0) + 1
            return
        decision = risk_evaluate(evaluation.signal, self._context(now, bar), self.cfg.limits)
        if not decision.approved:
            failed = next(c for c in decision.checks if not c.passed)
            self.rejections[failed.rule] = self.rejections.get(failed.rule, 0) + 1
            return
        if decision.volume is None or decision.risk_amount is None:
            return
        self.pending = (evaluation.signal, decision.volume, decision.risk_amount)


def expiry_bars(spec: ContractSpec, base_tf: Timeframe) -> int:
    """How many bars of `base_tf` a Rise/Fall lasts. Refuses what candles cannot resolve."""
    secs = spec.seconds
    if secs is None:
        raise BacktestError(
            f"A {spec.duration}-tick Rise/Fall cannot be backtested on {base_tf} candles: "
            "candles do not show individual ticks. Choose a duration of at least one bar "
            f"({base_tf.seconds // 60} minutes)."
        )
    if secs < base_tf.seconds:
        raise BacktestError(
            f"A {spec.duration}{spec.duration_unit} Rise/Fall is shorter than one {base_tf} "
            "candle: the data cannot show where the price was at expiry. Use data of a "
            f"timeframe of {secs // 60 or 1} minute(s) or less, or a longer duration."
        )
    return math.ceil(secs / base_tf.seconds)
