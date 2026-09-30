"""PAPER / SIMULATION broker.

An internal simulator implementing the full `BrokerAdapter` contract so the
entire pipeline (strategy → risk → execution → reconciliation → journal)
runs without MetaTrader 5. It is always reported as PAPER; nothing it does
is ever presented as a broker execution.

Realism choices (documented in docs/BROKERS.md):
* Market orders fill at ask (BUY) / bid (SELL) plus configured adverse slippage.
* Commission per lot per side; margin = notional / leverage; stop-out at 50 %.
* Stops/targets are evaluated on every completed base bar. If a bar touches
  both, the STOP is assumed first (conservative). Gaps fill at the bar open.
* Orders are idempotent by client_order_id.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from fxrobot.broker_engine.adapters.paper_market import SimMarket
from fxrobot.broker_engine.errors import (
    BrokerConnectionError,
    InsufficientMarginError,
    MarketClosedError,
    NotFoundError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import (
    AccountInfo,
    BrokerHealth,
    Candle,
    Deal,
    DealEntry,
    Order,
    OrderModification,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    SymbolInfo,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.market_data.conversion import conversion_rate

STOP_OUT_LEVEL = Decimal(50)  # percent margin level
MAX_DEALS_KEPT = 5000


@dataclass
class PaperConfig:
    account_id: str = "PAPER-1"
    currency: str = "USD"
    initial_balance: Decimal = Decimal(10000)
    leverage: int = 100
    commission_per_lot: Decimal = Decimal("3.5")  # per side
    slippage_points: int = 0


@dataclass
class FaultInjector:
    """Test/chaos hooks. Never enabled in normal operation."""

    disconnected: bool = False
    # Execute the next order, then pretend the response was lost.
    lose_next_response: bool = False
    # Fail the next order before it reaches the "broker" (outcome still unknown to caller).
    timeout_before_next_order: bool = False


@dataclass
class _Pos:
    id: str
    symbol: str
    side: Side
    volume: Decimal
    open_price: Decimal
    open_time: datetime
    sl: Decimal | None
    tp: Decimal | None
    client_order_id: str | None
    commission: Decimal = Decimal(0)


@dataclass
class _Pending:
    id: str
    symbol: str
    side: Side
    order_type: OrderType
    volume: Decimal
    price: Decimal
    sl: Decimal | None
    tp: Decimal | None
    client_order_id: str
    created: datetime


@dataclass
class _Account:
    balance: Decimal
    positions: dict[str, _Pos] = field(default_factory=dict)
    pending: dict[str, _Pending] = field(default_factory=dict)
    deals: list[Deal] = field(default_factory=list)
    results: dict[str, OrderResult] = field(default_factory=dict)
    next_id: int = 1


class PaperBroker(BrokerAdapter):
    connector_id = "paper"
    is_simulated = True

    def __init__(
        self,
        market: SimMarket,
        config: PaperConfig | None = None,
        *,
        state: dict[str, Any] | None = None,
        on_change: Callable[[dict[str, Any], bool], None] | None = None,
        faults: FaultInjector | None = None,
    ) -> None:
        self.market = market
        self.config = config or PaperConfig()
        self.faults = faults or FaultInjector()
        self._on_change = on_change
        self._connected = False
        self._lock = threading.RLock()
        self._specs = {s.name: s for s in market.symbols()}
        self._acct = _Account(balance=self.config.initial_balance)
        if state:
            self._restore(state)

    # ── connection ───────────────────────────────────────────────────────
    def connect(self) -> AccountInfo:
        self._check_link()
        self._connected = True
        return self.get_account()

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and not self.faults.disconnected

    def health(self) -> BrokerHealth:
        if self.faults.disconnected:
            return BrokerHealth(False, "Simulated disconnect")
        if self.market.exhausted():
            return BrokerHealth(self._connected, "Replay finished — no more data")
        return BrokerHealth(self._connected, f"{self.market.label} simulation")

    def _check_link(self) -> None:
        if self.faults.disconnected:
            raise BrokerConnectionError("Paper broker is disconnected (simulated fault)")

    def _require(self) -> None:
        self._check_link()
        if not self._connected:
            raise BrokerConnectionError("Paper broker is not connected")

    # ── time ─────────────────────────────────────────────────────────────
    def now(self) -> datetime:
        return self.market.now()

    def advance(self) -> None:
        with self._lock:
            bars = self.market.advance()
            if bars:
                self._process_bars(bars)

    def step(self, bars: int = 1) -> None:
        """Manually advance the simulation (tests, fast-forward)."""
        with self._lock:
            self._process_bars(self.market.step(bars))

    # ── account & market data ────────────────────────────────────────────
    def _quote(self, symbol: str) -> Quote | None:
        spec = self._specs.get(symbol)
        return self.market.quote(symbol, spec) if spec else None

    def _rate(self, from_ccy: str) -> Decimal | None:
        return conversion_rate(from_ccy, self.config.currency, self._quote)

    def _pnl(self, pos: _Pos, price: Decimal) -> Decimal:
        spec = self._specs[pos.symbol]
        raw = (price - pos.open_price) * pos.side.sign * pos.volume * spec.contract_size
        rate = self._rate(spec.quote_currency)
        return raw * rate if rate is not None else Decimal(0)

    def _exit_price(self, pos: _Pos) -> Decimal | None:
        quote = self._quote(pos.symbol)
        if quote is None:
            return None
        return quote.bid if pos.side is Side.BUY else quote.ask

    def _margin_for(self, symbol: str, volume: Decimal) -> Decimal:
        spec = self._specs[symbol]
        notional_base = volume * spec.contract_size
        rate = self._rate(spec.base_currency)
        if rate is None:
            raise OrderRejectedError(f"No conversion rate for {spec.base_currency}")
        return notional_base * rate / Decimal(self.config.leverage)

    def _totals(self) -> tuple[Decimal, Decimal]:
        unrealized = Decimal(0)
        margin = Decimal(0)
        for pos in self._acct.positions.values():
            price = self._exit_price(pos)
            if price is not None:
                unrealized += self._pnl(pos, price)
            margin += self._margin_for(pos.symbol, pos.volume)
        return unrealized, margin

    def get_account(self) -> AccountInfo:
        self._require_link_only()
        with self._lock:
            unrealized, margin = self._totals()
            equity = self._acct.balance + unrealized
            return AccountInfo(
                account_id=self.config.account_id,
                name="Paper account",
                server=f"2kFX Paper ({self.market.label})",
                currency=self.config.currency,
                environment=AccountEnvironment.PAPER,
                balance=_money(self._acct.balance),
                equity=_money(equity),
                margin=_money(margin),
                free_margin=_money(equity - margin),
                margin_level=_money(equity / margin * 100) if margin > 0 else None,
                leverage=self.config.leverage,
                trade_allowed=True,
            )

    def _require_link_only(self) -> None:
        self._check_link()

    def get_symbols(self) -> list[SymbolInfo]:
        self._check_link()
        return list(self._specs.values())

    def get_quote(self, symbol: str) -> Quote:
        self._check_link()
        if symbol not in self._specs:
            raise SymbolUnavailableError(f"Symbol {symbol} is not available")
        quote = self._quote(symbol)
        if quote is None:
            raise SymbolUnavailableError(f"No price for {symbol} yet")
        return quote

    def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        self._check_link()
        if symbol not in self._specs:
            raise SymbolUnavailableError(f"Symbol {symbol} is not available")
        return self.market.candles(symbol, timeframe, start, end)

    # ── trading state ────────────────────────────────────────────────────
    def get_positions(self) -> list[Position]:
        self._check_link()
        with self._lock:
            out = []
            for p in self._acct.positions.values():
                price = self._exit_price(p)
                out.append(
                    Position(
                        position_id=p.id,
                        symbol=p.symbol,
                        side=p.side,
                        volume=p.volume,
                        open_price=p.open_price,
                        open_time=p.open_time,
                        stop_loss=p.sl,
                        take_profit=p.tp,
                        unrealized_pnl=_money(self._pnl(p, price)) if price else Decimal(0),
                        client_order_id=p.client_order_id,
                    )
                )
            return out

    def get_orders(self) -> list[Order]:
        self._check_link()
        with self._lock:
            return [
                Order(
                    order_id=o.id,
                    symbol=o.symbol,
                    side=o.side,
                    order_type=o.order_type,
                    volume=o.volume,
                    status=OrderStatus.PENDING,
                    price=o.price,
                    stop_loss=o.sl,
                    take_profit=o.tp,
                    created_time=o.created,
                    client_order_id=o.client_order_id,
                )
                for o in self._acct.pending.values()
            ]

    def get_deals(self, start: datetime, end: datetime) -> list[Deal]:
        self._check_link()
        with self._lock:
            return [d for d in self._acct.deals if start <= d.time < end]

    def find_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        self._check_link()
        with self._lock:
            return self._acct.results.get(client_order_id)

    # ── trading actions ──────────────────────────────────────────────────
    def place_order(self, request: OrderRequest) -> OrderResult:
        self._require()
        with self._lock:
            existing = self._acct.results.get(request.client_order_id)
            if existing is not None:
                return existing  # idempotent: never execute twice
            if self.faults.timeout_before_next_order:
                self.faults.timeout_before_next_order = False
                raise OrderOutcomeUnknownError(
                    "Simulated timeout before execution", client_order_id=request.client_order_id
                )
            result = self._execute(request)
            self._acct.results[request.client_order_id] = result
            self._changed()
            if self.faults.lose_next_response:
                self.faults.lose_next_response = False
                raise OrderOutcomeUnknownError(
                    "Simulated lost response (order WAS executed)",
                    client_order_id=request.client_order_id,
                )
            return result

    def _validate(self, request: OrderRequest) -> SymbolInfo:
        spec = self._specs.get(request.symbol)
        if spec is None:
            raise SymbolUnavailableError(f"Symbol {request.symbol} is not available")
        if not self.market.is_open():
            raise MarketClosedError("Market is closed")
        vol = request.volume
        if vol < spec.volume_min or vol > spec.volume_max:
            raise OrderRejectedError(f"Volume {vol} outside [{spec.volume_min}, {spec.volume_max}]")
        if (vol / spec.volume_step) % 1 != 0:
            raise OrderRejectedError(f"Volume {vol} is not a multiple of {spec.volume_step}")
        return spec

    def _check_stops(
        self, side: Side, reference: Decimal, sl: Decimal | None, tp: Decimal | None
    ) -> None:
        if sl is not None and (sl - reference) * side.sign >= 0:
            raise OrderRejectedError("Invalid stops: stop loss on the wrong side of price")
        if tp is not None and (tp - reference) * side.sign <= 0:
            raise OrderRejectedError("Invalid stops: take profit on the wrong side of price")

    def _execute(self, request: OrderRequest) -> OrderResult:
        spec = self._validate(request)
        quote = self._quote(request.symbol)
        if quote is None:
            raise MarketClosedError("No price available")
        now = self.market.now()
        order_id = self._new_id()
        if request.order_type is OrderType.MARKET:
            slip = Decimal(self.config.slippage_points) * spec.point
            fill = quote.ask + slip if request.side is Side.BUY else quote.bid - slip
            self._check_stops(request.side, fill, request.stop_loss, request.take_profit)
            self._check_margin(request.symbol, request.volume)
            pos = self._open_position(
                request.symbol,
                request.side,
                request.volume,
                fill,
                request.stop_loss,
                request.take_profit,
                request.client_order_id,
                order_id,
                now,
            )
            return OrderResult(
                client_order_id=request.client_order_id,
                status=OrderStatus.FILLED,
                broker_order_id=order_id,
                broker_position_id=pos.id,
                filled_volume=request.volume,
                fill_price=fill,
                broker_code="PAPER_FILLED",
                broker_message="Simulated fill (PAPER)",
                time=now,
            )
        if request.price is None:  # also enforced by OrderRequest
            raise OrderRejectedError("Pending orders require a price")
        self._check_stops(request.side, request.price, request.stop_loss, request.take_profit)
        self._acct.pending[order_id] = _Pending(
            order_id,
            request.symbol,
            request.side,
            request.order_type,
            request.volume,
            request.price,
            request.stop_loss,
            request.take_profit,
            request.client_order_id,
            now,
        )
        return OrderResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.PENDING,
            broker_order_id=order_id,
            broker_code="PAPER_PLACED",
            broker_message="Simulated pending order (PAPER)",
            time=now,
        )

    def _check_margin(self, symbol: str, volume: Decimal) -> None:
        unrealized, margin = self._totals()
        free = self._acct.balance + unrealized - margin
        if self._margin_for(symbol, volume) > free:
            raise InsufficientMarginError("Not enough free margin")

    def _open_position(
        self,
        symbol: str,
        side: Side,
        volume: Decimal,
        price: Decimal,
        sl: Decimal | None,
        tp: Decimal | None,
        client_order_id: str | None,
        order_id: str,
        now: datetime,
    ) -> _Pos:
        commission = _money(self.config.commission_per_lot * volume)
        pos = _Pos(
            self._new_id(), symbol, side, volume, price, now, sl, tp, client_order_id, commission
        )
        self._acct.positions[pos.id] = pos
        self._acct.balance -= commission
        self._add_deal(
            Deal(
                self._new_id(),
                order_id,
                pos.id,
                symbol,
                side,
                DealEntry.IN,
                volume,
                price,
                now,
                Decimal(0),
                -commission,
                client_order_id=client_order_id,
                reason="EXPERT",
            )
        )
        return pos

    def _close(
        self,
        pos: _Pos,
        price: Decimal,
        volume: Decimal,
        reason: str,
        client_order_id: str | None = None,
    ) -> Deal:
        spec = self._specs[pos.symbol]
        part = _Pos(
            pos.id,
            pos.symbol,
            pos.side,
            volume,
            pos.open_price,
            pos.open_time,
            pos.sl,
            pos.tp,
            pos.client_order_id,
        )
        profit = _money(self._pnl(part, price))
        commission = _money(self.config.commission_per_lot * volume)
        self._acct.balance += profit - commission
        if volume >= pos.volume:
            del self._acct.positions[pos.id]
        else:
            pos.volume = (pos.volume - volume).quantize(spec.volume_step, rounding=ROUND_DOWN)
        deal = Deal(
            self._new_id(),
            None,
            pos.id,
            pos.symbol,
            pos.side.opposite,
            DealEntry.OUT,
            volume,
            price,
            self.market.now(),
            profit,
            -commission,
            client_order_id=client_order_id or pos.client_order_id,
            reason=reason,
        )
        self._add_deal(deal)
        return deal

    def modify_order(self, order_id: str, changes: OrderModification) -> OrderResult:
        self._require()
        with self._lock:
            pend = self._acct.pending.get(order_id)
            if pend is None:
                raise NotFoundError(f"Order {order_id} not found")
            price = changes.price or pend.price
            self._check_stops(pend.side, price, changes.stop_loss, changes.take_profit)
            pend.price, pend.sl, pend.tp = price, changes.stop_loss, changes.take_profit
            self._changed()
            return OrderResult(
                pend.client_order_id,
                OrderStatus.PENDING,
                broker_order_id=order_id,
                broker_message="Modified (PAPER)",
                time=self.market.now(),
            )

    def modify_position(
        self, position_id: str, stop_loss: Decimal | None, take_profit: Decimal | None
    ) -> OrderResult:
        self._require()
        with self._lock:
            pos = self._acct.positions.get(position_id)
            if pos is None:
                raise NotFoundError(f"Position {position_id} not found")
            price = self._exit_price(pos)
            if price is None:
                raise MarketClosedError("No price available")
            self._check_stops(pos.side, price, stop_loss, take_profit)
            pos.sl, pos.tp = stop_loss, take_profit
            self._changed()
            return OrderResult(
                pos.client_order_id,
                OrderStatus.FILLED,
                broker_position_id=position_id,
                broker_message="Position modified (PAPER)",
                time=self.market.now(),
            )

    def close_position(
        self, position_id: str, client_order_id: str, volume: Decimal | None = None
    ) -> OrderResult:
        self._require()
        with self._lock:
            existing = self._acct.results.get(client_order_id)
            if existing is not None:
                return existing
            pos = self._acct.positions.get(position_id)
            if pos is None:
                raise NotFoundError(f"Position {position_id} not found")
            if not self.market.is_open():
                raise MarketClosedError("Market is closed")
            price = self._exit_price(pos)
            if price is None:
                raise MarketClosedError("No price available")
            qty = pos.volume if volume is None or volume >= pos.volume else volume
            deal = self._close(pos, price, qty, "CLIENT", client_order_id)
            result = OrderResult(
                client_order_id,
                OrderStatus.FILLED,
                broker_order_id=deal.deal_id,
                broker_position_id=position_id,
                filled_volume=qty,
                fill_price=price,
                broker_code="PAPER_FILLED",
                broker_message="Simulated close (PAPER)",
                time=self.market.now(),
            )
            self._acct.results[client_order_id] = result
            self._changed()
            return result

    def cancel_order(self, order_id: str) -> OrderResult:
        self._require()
        with self._lock:
            pend = self._acct.pending.pop(order_id, None)
            if pend is None:
                raise NotFoundError(f"Order {order_id} not found")
            result = OrderResult(
                pend.client_order_id,
                OrderStatus.CANCELLED,
                broker_order_id=order_id,
                broker_message="Cancelled (PAPER)",
                time=self.market.now(),
            )
            self._acct.results[pend.client_order_id] = result
            self._changed()
            return result

    # ── simulation ───────────────────────────────────────────────────────
    def _process_bars(self, bars: list[tuple[str, Candle]]) -> None:
        changed = False
        for symbol, bar in bars:
            spec = self._specs[symbol]
            spread = Decimal(bar.spread_points or 0) * spec.point
            for pos in [p for p in self._acct.positions.values() if p.symbol == symbol]:
                exit_ = self._bar_exit(pos, bar, spread)
                if exit_:
                    price, reason = exit_
                    self._close(pos, price, pos.volume, reason)
                    changed = True
            for pend in [o for o in self._acct.pending.values() if o.symbol == symbol]:
                fill = self._pending_fill(pend, bar, spread)
                if fill is not None:
                    del self._acct.pending[pend.id]
                    try:
                        self._check_margin(symbol, pend.volume)
                    except InsufficientMarginError:
                        self._acct.results[pend.client_order_id] = OrderResult(
                            pend.client_order_id,
                            OrderStatus.CANCELLED,
                            broker_order_id=pend.id,
                            broker_message="Cancelled: insufficient margin at trigger (PAPER)",
                        )
                        continue
                    pos = self._open_position(
                        symbol,
                        pend.side,
                        pend.volume,
                        fill,
                        pend.sl,
                        pend.tp,
                        pend.client_order_id,
                        pend.id,
                        bar.time,
                    )
                    self._acct.results[pend.client_order_id] = OrderResult(
                        pend.client_order_id,
                        OrderStatus.FILLED,
                        broker_order_id=pend.id,
                        broker_position_id=pos.id,
                        filled_volume=pend.volume,
                        fill_price=fill,
                        broker_code="PAPER_FILLED",
                        broker_message="Pending order filled (PAPER)",
                        time=self.market.now(),
                    )
                    changed = True
        changed |= self._stop_out()
        if changed or bars:
            self._changed(important=changed)

    @staticmethod
    def _bar_exit(pos: _Pos, bar: Candle, spread: Decimal) -> tuple[Decimal, str] | None:
        """Exit (price, reason) if SL/TP was hit during `bar`. Stop wins ties."""
        if pos.side is Side.BUY:  # a long closes on the bid
            o, hi, lo = bar.open, bar.high, bar.low
            if pos.sl is not None and lo <= pos.sl:
                return (min(o, pos.sl), "SL")
            if pos.tp is not None and hi >= pos.tp:
                return (max(o, pos.tp), "TP")
        else:  # a short closes on the ask
            o, hi, lo = bar.open + spread, bar.high + spread, bar.low + spread
            if pos.sl is not None and hi >= pos.sl:
                return (max(o, pos.sl), "SL")
            if pos.tp is not None and lo <= pos.tp:
                return (min(o, pos.tp), "TP")
        return None

    @staticmethod
    def _pending_fill(pend: _Pending, bar: Candle, spread: Decimal) -> Decimal | None:
        if pend.side is Side.BUY:  # buys fill on the ask
            o, hi, lo = bar.open + spread, bar.high + spread, bar.low + spread
            if pend.order_type is OrderType.LIMIT and lo <= pend.price:
                return min(o, pend.price)
            if pend.order_type is OrderType.STOP and hi >= pend.price:
                return max(o, pend.price)
        else:
            o, hi, lo = bar.open, bar.high, bar.low
            if pend.order_type is OrderType.LIMIT and hi >= pend.price:
                return max(o, pend.price)
            if pend.order_type is OrderType.STOP and lo <= pend.price:
                return min(o, pend.price)
        return None

    def _stop_out(self) -> bool:
        closed = False
        while self._acct.positions:
            unrealized, margin = self._totals()
            if margin <= 0 or (self._acct.balance + unrealized) / margin * 100 >= STOP_OUT_LEVEL:
                break
            worst = min(
                self._acct.positions.values(),
                key=lambda p: self._pnl(p, self._exit_price(p) or p.open_price),
            )
            price = self._exit_price(worst) or worst.open_price
            self._close(worst, price, worst.volume, "SO")
            closed = True
        return closed

    # ── persistence ──────────────────────────────────────────────────────
    def _new_id(self) -> str:
        value = self._acct.next_id
        self._acct.next_id += 1
        return str(100000 + value)

    def _add_deal(self, deal: Deal) -> None:
        self._acct.deals.append(deal)
        if len(self._acct.deals) > MAX_DEALS_KEPT:
            del self._acct.deals[: len(self._acct.deals) - MAX_DEALS_KEPT]

    def _changed(self, important: bool = True) -> None:
        """Persist state. Trade operations are `important` (saved synchronously);
        routine price movement may be throttled by the owner."""
        if self._on_change is not None:
            self._on_change(self.export_state(), important)

    def export_state(self) -> dict[str, Any]:
        a = self._acct
        return {
            "version": 1,
            "market": self.market.state(),
            "balance": str(a.balance),
            "next_id": a.next_id,
            "positions": [_pos_to_json(p) for p in a.positions.values()],
            "pending": [_pending_to_json(o) for o in a.pending.values()],
            "deals": [_deal_to_json(d) for d in a.deals[-1000:]],
            "results": {k: _result_to_json(v) for k, v in list(a.results.items())[-2000:]},
        }

    def _restore(self, state: dict[str, Any]) -> None:
        a = self._acct
        a.balance = Decimal(state["balance"])
        a.next_id = int(state["next_id"])
        a.positions = {p["id"]: _pos_from_json(p) for p in state.get("positions", [])}
        a.pending = {o["id"]: _pending_from_json(o) for o in state.get("pending", [])}
        a.deals = [_deal_from_json(d) for d in state.get("deals", [])]
        a.results = {k: _result_from_json(v) for k, v in state.get("results", {}).items()}
        cursor = state.get("market", {}).get("cursor")
        if cursor:
            restored = datetime.fromisoformat(cursor)
            # Never jump backwards past history the market can serve.
            if restored > self.market.cursor - timedelta(days=3650):
                self.market.cursor = restored


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _pos_to_json(p: _Pos) -> dict[str, Any]:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "side": p.side.value,
        "volume": str(p.volume),
        "open_price": str(p.open_price),
        "open_time": p.open_time.isoformat(),
        "sl": _s(p.sl),
        "tp": _s(p.tp),
        "client_order_id": p.client_order_id,
        "commission": str(p.commission),
    }


def _pos_from_json(d: dict[str, Any]) -> _Pos:
    return _Pos(
        d["id"],
        d["symbol"],
        Side(d["side"]),
        Decimal(d["volume"]),
        Decimal(d["open_price"]),
        datetime.fromisoformat(d["open_time"]),
        _d(d["sl"]),
        _d(d["tp"]),
        d["client_order_id"],
        Decimal(d.get("commission", "0")),
    )


def _pending_to_json(o: _Pending) -> dict[str, Any]:
    return {
        "id": o.id,
        "symbol": o.symbol,
        "side": o.side.value,
        "type": o.order_type.value,
        "volume": str(o.volume),
        "price": str(o.price),
        "sl": _s(o.sl),
        "tp": _s(o.tp),
        "client_order_id": o.client_order_id,
        "created": o.created.isoformat(),
    }


def _pending_from_json(d: dict[str, Any]) -> _Pending:
    return _Pending(
        d["id"],
        d["symbol"],
        Side(d["side"]),
        OrderType(d["type"]),
        Decimal(d["volume"]),
        Decimal(d["price"]),
        _d(d["sl"]),
        _d(d["tp"]),
        d["client_order_id"],
        datetime.fromisoformat(d["created"]),
    )


def _deal_to_json(x: Deal) -> dict[str, Any]:
    return {
        "deal_id": x.deal_id,
        "order_id": x.order_id,
        "position_id": x.position_id,
        "symbol": x.symbol,
        "side": x.side.value,
        "entry": x.entry.value,
        "volume": str(x.volume),
        "price": str(x.price),
        "time": x.time.isoformat(),
        "profit": str(x.profit),
        "commission": str(x.commission),
        "swap": str(x.swap),
        "client_order_id": x.client_order_id,
        "reason": x.reason,
    }


def _deal_from_json(d: dict[str, Any]) -> Deal:
    return Deal(
        d["deal_id"],
        d["order_id"],
        d["position_id"],
        d["symbol"],
        Side(d["side"]),
        DealEntry(d["entry"]),
        Decimal(d["volume"]),
        Decimal(d["price"]),
        datetime.fromisoformat(d["time"]),
        Decimal(d["profit"]),
        Decimal(d["commission"]),
        Decimal(d["swap"]),
        client_order_id=d["client_order_id"],
        reason=d["reason"],
    )


def _result_to_json(r: OrderResult) -> dict[str, Any]:
    return {
        "client_order_id": r.client_order_id,
        "status": r.status.value,
        "broker_order_id": r.broker_order_id,
        "broker_position_id": r.broker_position_id,
        "filled_volume": str(r.filled_volume),
        "fill_price": _s(r.fill_price),
        "broker_code": r.broker_code,
        "broker_message": r.broker_message,
        "time": r.time.isoformat() if r.time else None,
    }


def _result_from_json(d: dict[str, Any]) -> OrderResult:
    return OrderResult(
        d["client_order_id"],
        OrderStatus(d["status"]),
        d["broker_order_id"],
        d["broker_position_id"],
        Decimal(d["filled_volume"]),
        _d(d["fill_price"]),
        d["broker_code"],
        d["broker_message"],
        datetime.fromisoformat(d["time"]) if d.get("time") else None,
    )
