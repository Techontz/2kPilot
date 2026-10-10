"""PAPER broker: fills, costs, margin, validation, SL/TP/pending simulation,
stop-out, persistence, time capping and fault injection.

Most tests drive the broker with a `ReplayMarket` of hand-made bars so every
price (and therefore every P&L figure) is exact.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fxrobot.broker_engine.adapters.paper import (
    FaultInjector,
    PaperBroker,
    PaperConfig,
)
from fxrobot.broker_engine.adapters.paper_market import (
    MAX_STEPS_PER_ADVANCE,
    ReplayMarket,
    SyntheticMarket,
)
from fxrobot.broker_engine.errors import (
    BrokerConnectionError,
    InsufficientMarginError,
    MarketClosedError,
    NotFoundError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.models import (
    Candle,
    DealEntry,
    OrderModification,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.market_data.synthetic import DEFAULT_SPECS
from tests.paper_helpers import SIM_START, make_paper

M15 = timedelta(minutes=15)
D = Decimal
Row = tuple[str, str, str, str]  # open, high, low, close
FLAT: Row = ("1.10000", "1.10000", "1.10000", "1.10000")
SPREAD = 10  # points → 0.00010 on EURUSD, 0.010 on USDJPY


def _bars(start: datetime, rows: Sequence[Row], spread: int) -> list[Candle]:
    return [
        Candle(start + i * M15, D(o), D(h), D(lo), D(c), 100, spread)
        for i, (o, h, lo, c) in enumerate(rows)
    ]


def replay(
    future: Sequence[Row] = (FLAT, FLAT),
    *,
    jpy_future: Sequence[Row] | None = None,
    start: datetime = SIM_START,
    balance: str = "10000",
    commission: str = "3.5",
    slippage: int = 0,
    leverage: int = 100,
    faults: FaultInjector | None = None,
    state: dict[str, Any] | None = None,
    on_change: Any = None,
    connect: bool = True,
) -> PaperBroker:
    """A connected broker whose EURUSD quote is bid 1.10000 / ask 1.10010 at `start`.

    Future bar i (open time start + i*15m) completes on the (i+1)-th `step()`.
    """
    bars = {"EURUSD": _bars(start - M15, [FLAT, *future], SPREAD)}
    specs = {"EURUSD": DEFAULT_SPECS["EURUSD"].symbol_info()}
    if jpy_future is not None:
        flat_jpy: Row = ("150.000", "150.000", "150.000", "150.000")
        bars["USDJPY"] = _bars(start - M15, [flat_jpy, *jpy_future], SPREAD)
        specs["USDJPY"] = DEFAULT_SPECS["USDJPY"].symbol_info()
    market = ReplayMarket(
        bars=bars, specs=specs, base_timeframe=Timeframe.M15, start=start, seconds_per_bar=0
    )
    broker = PaperBroker(
        market,
        PaperConfig(
            initial_balance=D(balance),
            commission_per_lot=D(commission),
            slippage_points=slippage,
            leverage=leverage,
        ),
        faults=faults,
        state=state,
        on_change=on_change,
    )
    if connect:
        broker.connect()
    return broker


def req(
    coid: str = "c1",
    side: Side = Side.BUY,
    volume: str = "1",
    sl: str | None = None,
    tp: str | None = None,
    order_type: OrderType = OrderType.MARKET,
    price: str | None = None,
    symbol: str = "EURUSD",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        symbol=symbol,
        side=side,
        order_type=order_type,
        volume=D(volume),
        stop_loss=D(sl) if sl else None,
        take_profit=D(tp) if tp else None,
        price=D(price) if price else None,
    )


def all_deals(broker: PaperBroker) -> list[Any]:
    return broker.get_deals(datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


# ── identity ─────────────────────────────────────────────────────────────────


def test_paper_account_is_always_paper_and_simulated() -> None:
    broker = replay()
    account = broker.get_account()
    assert account.environment is AccountEnvironment.PAPER
    assert broker.is_simulated is True
    assert account.server == "2kPilot Paper (REPLAY)"
    assert account.balance == D("10000.00")
    assert account.margin == D("0.00")
    assert account.margin_level is None
    assert broker.health().detail == "REPLAY simulation"


def test_quote_from_last_closed_bar_plus_spread() -> None:
    quote = replay().get_quote("EURUSD")
    assert (quote.bid, quote.ask) == (D("1.10000"), D("1.10010"))
    assert quote.time == SIM_START


def test_unknown_symbol_everywhere() -> None:
    broker = replay()
    with pytest.raises(SymbolUnavailableError):
        broker.get_quote("GBPUSD")
    with pytest.raises(SymbolUnavailableError):
        broker.get_candles("GBPUSD", Timeframe.M15, SIM_START - M15, SIM_START)
    with pytest.raises(SymbolUnavailableError):
        broker.place_order(req(symbol="GBPUSD"))


# ── market fills & costs ─────────────────────────────────────────────────────


def test_market_buy_fills_at_ask_and_sell_at_bid() -> None:
    broker = replay()
    buy = broker.place_order(req("b1", Side.BUY))
    sell = broker.place_order(req("s1", Side.SELL))
    assert buy.status is OrderStatus.FILLED
    assert buy.fill_price == D("1.10010")
    assert sell.fill_price == D("1.10000")
    assert buy.filled_volume == D(1)
    assert buy.broker_code == "PAPER_FILLED"
    assert "PAPER" in (buy.broker_message or "")
    assert buy.time == SIM_START


def test_slippage_is_always_adverse() -> None:
    broker = replay(slippage=3)
    assert broker.place_order(req("b1", Side.BUY)).fill_price == D("1.10013")
    assert broker.place_order(req("s1", Side.SELL)).fill_price == D("1.09997")


def test_commission_charged_per_lot_per_side() -> None:
    broker = replay()
    result = broker.place_order(req(volume="0.5"))
    assert broker.get_account().balance == D("9998.25")
    [deal] = all_deals(broker)
    assert deal.entry is DealEntry.IN
    assert deal.commission == D("-1.75")
    assert deal.profit == D(0)
    assert deal.price == D("1.10010")
    assert deal.client_order_id == "c1"
    assert deal.position_id == result.broker_position_id
    broker.close_position(result.broker_position_id or "", "x1")
    # Closing a BUY at the bid loses the spread: 0.5 * 100000 * 0.0001 = 5.00.
    assert broker.get_account().balance == D("10000") - D("1.75") * 2 - D("5.00")


def test_account_margin_equity_and_level_exact() -> None:
    broker = replay()
    broker.place_order(req(volume="1"))
    account = broker.get_account()
    margin = D(100000) * D("1.10005") / 100  # notional in USD at the mid / leverage
    equity = D("10000") - D("3.50") - D("10.00")  # spread loss marked to the bid
    assert account.balance == D("9996.50")
    assert account.equity == equity
    assert account.margin == margin.quantize(D("0.01"))
    assert account.free_margin == (equity - margin).quantize(D("0.01"))
    assert account.margin_level == (equity / margin * 100).quantize(D("0.01"))
    [pos] = broker.get_positions()
    assert pos.unrealized_pnl == D("-10.00")


def test_cross_currency_pnl_and_margin_convert_to_account_currency() -> None:
    broker = replay(jpy_future=[("150.000", "151.000", "150.000", "151.000")])
    result = broker.place_order(req(symbol="USDJPY", volume="1"))
    assert result.fill_price == D("150.010")
    # USD base → margin needs no conversion: 100000 / 100.
    assert broker.get_account().margin == D("1000.00")
    broker.step()
    [pos] = broker.get_positions()
    jpy_pnl = (D("151.000") - D("150.010")) * 100000
    expected = (jpy_pnl * (D(1) / D("151.005"))).quantize(D("0.01"))
    assert pos.unrealized_pnl == expected


def test_insufficient_margin_rejected_without_side_effects() -> None:
    broker = replay(balance="1000")
    with pytest.raises(InsufficientMarginError):
        broker.place_order(req(volume="1"))  # needs 1100.05
    assert broker.get_positions() == []
    assert broker.get_account().balance == D("1000.00")
    assert broker.find_order_by_client_id("c1") is None
    # A smaller order fits.
    assert broker.place_order(req("c2", volume="0.5")).status is OrderStatus.FILLED


# ── validation ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("side", "sl", "tp"),
    [
        (Side.BUY, "1.10020", None),  # SL above the ask fill
        (Side.BUY, "1.10010", None),  # SL exactly at the fill
        (Side.BUY, None, "1.10000"),  # TP below the fill
        (Side.SELL, "1.09990", None),  # SL below the bid fill
        (Side.SELL, None, "1.10000"),  # TP at the fill
    ],
)
def test_invalid_stops_rejected(side: Side, sl: str | None, tp: str | None) -> None:
    broker = replay()
    with pytest.raises(OrderRejectedError, match="Invalid stops"):
        broker.place_order(req(side=side, sl=sl, tp=tp))
    assert broker.get_positions() == []


def test_valid_stops_accepted_and_reported() -> None:
    broker = replay()
    broker.place_order(req(sl="1.09900", tp="1.10200"))
    [pos] = broker.get_positions()
    assert (pos.stop_loss, pos.take_profit) == (D("1.09900"), D("1.10200"))
    assert pos.client_order_id == "c1"


@pytest.mark.parametrize("volume", ["0.001", "50.01", "0.015", "1.005"])
def test_volume_limits_and_step(volume: str) -> None:
    broker = replay()
    with pytest.raises(OrderRejectedError, match="Volume"):
        broker.place_order(req(volume=volume))


@pytest.mark.parametrize("volume", ["0.01", "50", "1.23"])
def test_volume_boundaries_accepted(volume: str) -> None:
    broker = replay(balance="1000000")
    assert broker.place_order(req(volume=volume)).filled_volume == D(volume)


def test_market_closed_on_saturday() -> None:
    saturday = datetime(2025, 3, 8, 12, 0, tzinfo=UTC)
    broker = replay(start=saturday)
    with pytest.raises(MarketClosedError):
        broker.place_order(req())
    with pytest.raises(MarketClosedError):
        broker.place_order(req(order_type=OrderType.LIMIT, price="1.09000"))


def test_market_closes_friday_evening_blocks_close() -> None:
    friday = datetime(2025, 3, 7, 20, 30, tzinfo=UTC)
    broker = replay(start=friday)
    pid = broker.place_order(req()).broker_position_id or ""
    broker.step(2)  # → Friday 21:00 UTC, market closed
    with pytest.raises(MarketClosedError):
        broker.close_position(pid, "x1")
    assert len(broker.get_positions()) == 1


def test_replay_exhausted_is_closed() -> None:
    broker = replay(future=[FLAT])
    broker.step()
    assert broker.market.exhausted()
    assert "Replay finished" in broker.health().detail
    with pytest.raises(MarketClosedError):
        broker.place_order(req())
    broker.step(5)  # no more data: stays put
    assert broker.now() == SIM_START + M15


# ── idempotency ──────────────────────────────────────────────────────────────


def test_place_order_idempotent_by_client_id() -> None:
    broker = replay()
    first = broker.place_order(req())
    second = broker.place_order(req(volume="2"))  # same id, different payload
    assert second == first
    assert len(broker.get_positions()) == 1
    assert broker.get_account().balance == D("9996.50")


def test_close_idempotent_by_client_id() -> None:
    broker = replay()
    pid = broker.place_order(req()).broker_position_id or ""
    first = broker.close_position(pid, "x1")
    assert broker.close_position(pid, "x1") == first  # position is gone, result replayed
    assert len([d for d in all_deals(broker) if d.entry is DealEntry.OUT]) == 1
    assert broker.find_order_by_client_id("x1") == first


def test_close_unknown_position() -> None:
    with pytest.raises(NotFoundError):
        replay().close_position("nope", "x1")


# ── SL / TP simulation ───────────────────────────────────────────────────────


def test_long_stop_loss_hit_exact_pnl() -> None:
    broker = replay(future=[("1.10000", "1.10020", "1.09850", "1.09950"), FLAT])
    pid = broker.place_order(req(sl="1.09900")).broker_position_id
    broker.step()
    assert broker.get_positions() == []
    out = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert len(out) == 1
    assert out[0].reason == "SL"
    assert out[0].price == D("1.09900")
    assert out[0].profit == D("-110.00")
    assert out[0].side is Side.SELL
    assert out[0].position_id == pid
    assert broker.get_account().balance == D("10000") - D("110.00") - D("7.00")


def test_long_take_profit_hit() -> None:
    broker = replay(future=[("1.10000", "1.10250", "1.10000", "1.10100"), FLAT])
    broker.place_order(req(tp="1.10200"))
    broker.step()
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert (out.reason, out.price, out.profit) == ("TP", D("1.10200"), D("190.00"))


def test_stop_wins_when_bar_touches_both() -> None:
    broker = replay(future=[("1.10000", "1.10300", "1.09800", "1.10000"), FLAT])
    broker.place_order(req(sl="1.09900", tp="1.10200"))
    broker.step()
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert out.reason == "SL"
    assert out.price == D("1.09900")


def test_gap_through_stop_fills_at_open() -> None:
    broker = replay(future=[("1.09700", "1.09800", "1.09600", "1.09750"), FLAT])
    broker.place_order(req(sl="1.09900"))
    broker.step()
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert out.price == D("1.09700")  # worse than the stop
    assert out.profit == D("-310.00")


def test_gap_through_target_fills_at_open() -> None:
    broker = replay(future=[("1.10500", "1.10600", "1.10400", "1.10550"), FLAT])
    broker.place_order(req(tp="1.10200"))
    broker.step()
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert (out.reason, out.price) == ("TP", D("1.10500"))


def test_short_stop_evaluated_on_ask() -> None:
    # Bid high 1.10095 never reaches 1.10100, but the ask (bid + 10 points) does.
    broker = replay(future=[("1.10000", "1.10095", "1.09990", "1.10000"), FLAT])
    broker.place_order(req(side=Side.SELL, sl="1.10100"))
    broker.step()
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert (out.reason, out.price, out.side) == ("SL", D("1.10100"), Side.BUY)
    assert out.profit == D("-100.00")


def test_short_target_needs_the_ask_to_reach_it() -> None:
    # Bid low 1.09895 is below the TP, but the ask low (1.09905) is not → no exit.
    broker = replay(future=[("1.10000", "1.10000", "1.09895", "1.09950"), FLAT])
    broker.place_order(req(side=Side.SELL, tp="1.09900"))
    broker.step()
    assert len(broker.get_positions()) == 1


def test_untouched_stops_keep_position_open() -> None:
    broker = replay(future=[("1.10000", "1.10100", "1.09950", "1.10050"), FLAT])
    broker.place_order(req(sl="1.09900", tp="1.10200"))
    broker.step()
    [pos] = broker.get_positions()
    assert pos.unrealized_pnl == D("40.00")  # (1.10050 - 1.10010) * 100000


# ── pending orders ───────────────────────────────────────────────────────────


def test_buy_limit_triggers_on_ask() -> None:
    broker = replay(future=[("1.10000", "1.10000", "1.09930", "1.09980"), FLAT])
    placed = broker.place_order(
        req("p1", order_type=OrderType.LIMIT, price="1.09950", sl="1.09800")
    )
    assert placed.status is OrderStatus.PENDING
    assert placed.broker_code == "PAPER_PLACED"
    [order] = broker.get_orders()
    assert (order.order_type, order.price, order.status) == (
        OrderType.LIMIT,
        D("1.09950"),
        OrderStatus.PENDING,
    )
    assert broker.get_account().balance == D("10000.00")  # no commission until filled
    broker.step()
    assert broker.get_orders() == []
    filled = broker.find_order_by_client_id("p1")
    assert filled is not None
    assert filled.status is OrderStatus.FILLED
    assert filled.fill_price == D("1.09950")
    assert filled.broker_order_id == placed.broker_order_id
    [pos] = broker.get_positions()
    assert (pos.open_price, pos.stop_loss, pos.client_order_id) == (
        D("1.09950"),
        D("1.09800"),
        "p1",
    )
    assert pos.open_time == SIM_START
    assert broker.get_account().balance == D("9996.50")


def test_buy_limit_not_triggered_when_only_bid_reaches_it() -> None:
    # Bid low 1.09945 ≤ 1.09950, but a buy fills on the ask (1.09955) → not triggered.
    broker = replay(future=[("1.10000", "1.10000", "1.09945", "1.09980"), FLAT])
    broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09950"))
    broker.step()
    assert len(broker.get_orders()) == 1
    assert broker.get_positions() == []


def test_buy_stop_triggers_at_price() -> None:
    broker = replay(future=[("1.10000", "1.10095", "1.10000", "1.10050"), FLAT])
    broker.place_order(req("p1", order_type=OrderType.STOP, price="1.10100"))
    broker.step()
    [pos] = broker.get_positions()
    assert pos.open_price == D("1.10100")


def test_sell_limit_triggers_on_bid() -> None:
    broker = replay(future=[("1.10000", "1.10150", "1.10000", "1.10100"), FLAT])
    broker.place_order(req("p1", Side.SELL, order_type=OrderType.LIMIT, price="1.10100"))
    broker.step()
    [pos] = broker.get_positions()
    assert (pos.side, pos.open_price) == (Side.SELL, D("1.10100"))


def test_sell_stop_gap_fills_at_open() -> None:
    broker = replay(future=[("1.09800", "1.09850", "1.09700", "1.09750"), FLAT])
    broker.place_order(req("p1", Side.SELL, order_type=OrderType.STOP, price="1.09900"))
    broker.step()
    [pos] = broker.get_positions()
    assert pos.open_price == D("1.09800")  # worse than the stop price


def test_pending_invalid_stops_rejected() -> None:
    broker = replay()
    with pytest.raises(OrderRejectedError, match="Invalid stops"):
        broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09950", sl="1.10000"))
    assert broker.get_orders() == []


def test_pending_cancelled_when_margin_insufficient_at_trigger() -> None:
    broker = replay(balance="1000", future=[("1.10000", "1.10000", "1.09930", "1.09980"), FLAT])
    broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09950"))
    broker.step()
    assert broker.get_positions() == []
    assert broker.get_orders() == []
    result = broker.find_order_by_client_id("p1")
    assert result is not None
    assert result.status is OrderStatus.CANCELLED
    assert "insufficient margin" in (result.broker_message or "")


def test_cancel_pending_order() -> None:
    broker = replay()
    oid = broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09000")).broker_order_id
    cancelled = broker.cancel_order(oid or "")
    assert cancelled.status is OrderStatus.CANCELLED
    assert broker.get_orders() == []
    assert broker.find_order_by_client_id("p1") == cancelled
    with pytest.raises(NotFoundError):
        broker.cancel_order(oid or "")


def test_modify_pending_order() -> None:
    broker = replay()
    oid = broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09500")).broker_order_id
    assert oid is not None
    broker.modify_order(
        oid, OrderModification(price=D("1.09400"), stop_loss=D("1.09000"), take_profit=None)
    )
    [order] = broker.get_orders()
    assert (order.price, order.stop_loss, order.take_profit) == (D("1.09400"), D("1.09000"), None)
    with pytest.raises(OrderRejectedError):
        broker.modify_order(oid, OrderModification(stop_loss=D("1.09500")))  # above the price
    [order] = broker.get_orders()
    assert order.stop_loss == D("1.09000")  # unchanged after the rejection
    with pytest.raises(NotFoundError):
        broker.modify_order("nope", OrderModification())


# ── position management ──────────────────────────────────────────────────────


def test_partial_close() -> None:
    broker = replay(future=[("1.10000", "1.10100", "1.10000", "1.10100"), FLAT])
    pid = broker.place_order(req(volume="1")).broker_position_id or ""
    broker.step()  # bid now 1.10100
    result = broker.close_position(pid, "x1", D("0.4"))
    assert result.filled_volume == D("0.4")
    assert result.fill_price == D("1.10100")
    [pos] = broker.get_positions()
    assert pos.volume == D("0.60")
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert out.volume == D("0.4")
    assert out.profit == D("36.00")  # (1.10100 - 1.10010) * 0.4 * 100000
    assert out.commission == D("-1.40")
    assert out.reason == "CLIENT"
    assert broker.get_account().balance == D("10000") - D("3.50") + D("36.00") - D("1.40")


def test_close_more_than_position_closes_all() -> None:
    broker = replay()
    pid = broker.place_order(req(volume="0.5")).broker_position_id or ""
    result = broker.close_position(pid, "x1", D("3"))
    assert result.filled_volume == D("0.5")
    assert broker.get_positions() == []


def test_modify_position_validation() -> None:
    broker = replay()
    pid = broker.place_order(req(volume="1")).broker_position_id or ""
    broker.modify_position(pid, D("1.09800"), D("1.10500"))
    [pos] = broker.get_positions()
    assert (pos.stop_loss, pos.take_profit) == (D("1.09800"), D("1.10500"))
    # A long's stop must be below the current bid (1.10000).
    with pytest.raises(OrderRejectedError, match="stop loss"):
        broker.modify_position(pid, D("1.10000"), None)
    with pytest.raises(OrderRejectedError, match="take profit"):
        broker.modify_position(pid, None, D("1.09990"))
    [pos] = broker.get_positions()
    assert (pos.stop_loss, pos.take_profit) == (D("1.09800"), D("1.10500"))
    broker.modify_position(pid, None, None)  # removing both is allowed
    [pos] = broker.get_positions()
    assert (pos.stop_loss, pos.take_profit) == (None, None)
    with pytest.raises(NotFoundError):
        broker.modify_position("nope", None, None)


def test_stop_out_closes_positions_below_50_percent_margin_level() -> None:
    broker = replay(balance="1200", future=[("1.10000", "1.10000", "1.09300", "1.09300"), FLAT])
    broker.place_order(req(volume="1"))
    broker.step()
    assert broker.get_positions() == []
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert out.reason == "SO"
    assert out.price == D("1.09300")
    assert out.profit == D("-710.00")
    assert broker.get_account().balance == D("1200") - D("7.00") - D("710.00")


def test_no_stop_out_above_threshold() -> None:
    broker = replay(balance="1200", future=[("1.10000", "1.10000", "1.09700", "1.09700"), FLAT])
    broker.place_order(req(volume="1"))
    broker.step()
    assert len(broker.get_positions()) == 1  # level ≈ 81 %
    level = broker.get_account().margin_level
    assert level is not None
    assert level > 50


def test_stop_out_closes_worst_position_first() -> None:
    # Long loses, short gains; closing the long restores the margin level.
    broker = replay(balance="1300", future=[("1.10000", "1.10000", "1.09200", "1.09200"), FLAT])
    broker.place_order(req("long", Side.BUY, volume="1"))
    broker.place_order(req("short", Side.SELL, volume="0.1"))
    broker.step()
    [remaining] = broker.get_positions()
    assert remaining.client_order_id == "short"
    [out] = [d for d in all_deals(broker) if d.entry is DealEntry.OUT]
    assert (out.reason, out.client_order_id) == ("SO", "long")


# ── persistence ──────────────────────────────────────────────────────────────


def test_export_restore_round_trip() -> None:
    future = [FLAT, FLAT, FLAT]
    broker = replay(future=future)
    broker.place_order(req("m1", volume="0.5", sl="1.09000", tp="1.11000"))
    broker.place_order(req("p1", order_type=OrderType.LIMIT, price="1.09000"))
    pid = broker.place_order(req("m2", Side.SELL, volume="0.2")).broker_position_id or ""
    broker.close_position(pid, "x1", D("0.1"))
    broker.step()
    state = broker.export_state()
    restored_state = json.loads(json.dumps(state))  # must be plain JSON

    restored = replay(future=future, state=restored_state)
    assert restored.now() == broker.now() == SIM_START + M15
    assert restored.get_account() == broker.get_account()
    assert restored.get_positions() == broker.get_positions()
    assert restored.get_orders() == broker.get_orders()
    assert all_deals(restored) == all_deals(broker)
    for coid in ("m1", "p1", "m2", "x1"):
        assert restored.find_order_by_client_id(coid) == broker.find_order_by_client_id(coid)
    # Idempotency survives a restart: the same client id never executes twice.
    assert restored.place_order(req("m1", volume="0.5")) == broker.find_order_by_client_id("m1")
    assert len(restored.get_positions()) == 2
    # New ids continue after the restored counter (no collisions).
    new = restored.place_order(req("m3"))
    existing = {p.position_id for p in broker.get_positions()} | {
        d.deal_id for d in all_deals(broker)
    }
    assert new.broker_order_id not in existing
    assert new.broker_position_id not in existing


def test_on_change_receives_state_for_trades_and_bars() -> None:
    calls: list[tuple[dict[str, Any], bool]] = []
    broker = replay(on_change=lambda state, important: calls.append((state, important)))
    broker.place_order(req())
    assert calls[-1][1] is True
    assert len(calls[-1][0]["positions"]) == 1
    broker.step()  # a routine bar with no trade activity
    assert calls[-1][1] is False


# ── simulated time ───────────────────────────────────────────────────────────


class FakeWall:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_step_never_runs_past_real_time() -> None:
    real_now = SIM_START + timedelta(minutes=37, seconds=30)
    market = SyntheticMarket(
        seed=1, symbols=("EURUSD",), start=SIM_START, seconds_per_bar=0, utcnow=lambda: real_now
    )
    broker = PaperBroker(market)
    broker.connect()
    broker.step(50)
    assert broker.now() == SIM_START + timedelta(minutes=37)  # floor(10:37:30) = 10:37
    broker.step(10)
    assert broker.now() == SIM_START + timedelta(minutes=37)
    # Candles never include bars that have not closed in simulated time.
    later = SIM_START + timedelta(days=1)
    candles = broker.get_candles("EURUSD", Timeframe.M15, SIM_START - timedelta(hours=1), later)
    assert candles[-1].time == SIM_START + M15
    assert all(c.time + M15 <= broker.now() for c in candles)
    minutes = broker.get_candles("EURUSD", Timeframe.M1, SIM_START, later)
    assert minutes[-1].time == SIM_START + timedelta(minutes=36)


def test_advance_paced_by_wall_clock_and_capped() -> None:
    """`seconds_per_bar` is wall seconds per 15 simulated minutes (1-minute steps)."""
    wall = FakeWall()
    market = SyntheticMarket(
        seed=1, symbols=("EURUSD",), start=SIM_START, seconds_per_bar=2.0, wall_clock=wall
    )
    broker = PaperBroker(market)
    broker.connect()
    broker.advance()
    assert broker.now() == SIM_START
    wall.t = 5.0  # 2.5 × 15 minutes elapsed → 37 whole minutes
    broker.advance()
    assert broker.now() == SIM_START + timedelta(minutes=37)
    wall.t = 5.05  # carry-over: less than one more minute
    broker.advance()
    assert broker.now() == SIM_START + timedelta(minutes=37)
    wall.t = 10_000.0
    broker.advance()
    assert broker.now() == SIM_START + timedelta(minutes=37 + MAX_STEPS_PER_ADVANCE)


def test_advance_stops_at_the_strategy_bar_close() -> None:
    """The engine caps each advance at the next close of the strategy's timeframe,
    so a fast-forwarding account evaluates every candle (none is skipped)."""
    wall = FakeWall()
    market = SyntheticMarket(
        seed=1, symbols=("EURUSD",), start=SIM_START, seconds_per_bar=2.0, wall_clock=wall
    )
    broker = PaperBroker(market)
    broker.connect()
    m5 = Timeframe.M5
    closes = []
    for tick in range(1, 7):
        wall.t = 2.0 * tick  # 15 simulated minutes per tick if nothing held it back
        broker.advance(m5.floor(broker.now()) + m5.delta)
        closes.append(broker.now())
    assert closes == [SIM_START + timedelta(minutes=5 * i) for i in range(1, 7)]
    # Without a cap the same wall time covers 15 minutes per tick.
    wall.t += 2.0
    broker.advance()
    assert broker.now() == closes[-1] + M15


def test_paper_prices_do_not_depend_on_when_the_market_was_built() -> None:
    """Prices are a pure function of (seed, symbol, time): starting the simulation
    elsewhere, restarting it, or a different 'today' never changes a bar."""
    early = SyntheticMarket(
        seed=4, symbols=("EURUSD",), start=SIM_START - timedelta(days=40), seconds_per_bar=0
    )
    late = SyntheticMarket(seed=4, symbols=("EURUSD",), start=SIM_START, seconds_per_bar=0)
    early.cursor = late.cursor
    window = (SIM_START - timedelta(days=3), SIM_START)
    for tf in (Timeframe.M1, Timeframe.M5, Timeframe.H1):
        assert early.candles("EURUSD", tf, *window) == late.candles("EURUSD", tf, *window)
    assert early.quote("EURUSD", early.symbols()[0]) == late.quote("EURUSD", late.symbols()[0])
    other_seed = SyntheticMarket(seed=5, symbols=("EURUSD",), start=SIM_START, seconds_per_bar=0)
    assert other_seed.candles("EURUSD", Timeframe.H1, *window) != late.candles(
        "EURUSD", Timeframe.H1, *window
    )


def test_paper_timeframes_are_consistent_aggregations_of_one_minute_bars() -> None:
    from fxrobot.market_data.resample import resample

    market = SyntheticMarket(seed=2, symbols=("EURUSD", "R_75"), start=SIM_START, seconds_per_bar=0)
    # Cross a weekend: 2025-02-28 is a Friday.
    start = datetime(2025, 2, 27, tzinfo=UTC)
    end = SIM_START
    for symbol in ("EURUSD", "R_75"):
        m1 = market.candles(symbol, Timeframe.M1, start, end)
        assert all(
            b.time - a.time == timedelta(minutes=1) or symbol == "EURUSD"
            for a, b in itertools.pairwise(m1)
        )
        for tf in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
            got = market.candles(symbol, tf, start, end)
            assert got, (symbol, tf)
            assert got == resample(m1, tf, until=end), (symbol, tf)
        m5 = market.candles(symbol, Timeframe.M5, start, end)
        m15 = market.candles(symbol, Timeframe.M15, start, end)
        assert m15 == resample(m5, Timeframe.M15, until=end)
    # FX hides the weekend; the index trades around the clock.
    fx = market.candles("EURUSD", Timeframe.H1, start, end)
    assert not any(c.time.weekday() == 5 for c in fx)
    index = market.candles("R_75", Timeframe.H1, start, end)
    assert any(c.time.weekday() == 5 for c in index)


def test_quotes_and_settlement_read_the_same_one_minute_bars() -> None:
    broker = make_paper()
    bar = broker.get_candles(
        "EURUSD", Timeframe.M1, broker.now() - timedelta(hours=1), broker.now()
    )[-1]
    quote = broker.get_quote("EURUSD")
    assert bar.time == broker.now() - timedelta(minutes=1)
    assert quote.bid == bar.close
    assert quote.ask == bar.close + D(bar.spread_points or 0) * D("0.00001")
    broker.step(1)
    assert (
        broker.get_quote("EURUSD").bid
        == broker.get_candles(
            "EURUSD", Timeframe.M1, broker.now() - timedelta(minutes=5), broker.now()
        )[-1].close
    )


def test_zero_pacing_never_advances_automatically() -> None:
    broker = make_paper()
    broker.advance()
    assert broker.now() == SIM_START


# ── connection & fault injection ─────────────────────────────────────────────


def test_trading_requires_connection() -> None:
    broker = replay(connect=False)
    assert not broker.is_connected
    with pytest.raises(BrokerConnectionError):
        broker.place_order(req())
    broker.connect()
    broker.disconnect()
    with pytest.raises(BrokerConnectionError):
        broker.close_position("x", "y")


def test_simulated_disconnect() -> None:
    faults = FaultInjector()
    broker = replay(faults=faults)
    faults.disconnected = True
    assert not broker.is_connected
    assert broker.health().connected is False
    for call in (
        broker.get_account,
        broker.get_positions,
        lambda: broker.get_quote("EURUSD"),
        lambda: broker.place_order(req()),
        broker.connect,
    ):
        with pytest.raises(BrokerConnectionError):
            call()
    faults.disconnected = False
    assert broker.is_connected


def test_timeout_before_order_does_not_execute() -> None:
    faults = FaultInjector(timeout_before_next_order=True)
    broker = replay(faults=faults)
    with pytest.raises(OrderOutcomeUnknownError) as info:
        broker.place_order(req())
    assert info.value.client_order_id == "c1"
    assert broker.get_positions() == []
    assert broker.find_order_by_client_id("c1") is None  # reconciliation: not executed
    assert faults.timeout_before_next_order is False  # one-shot
    assert broker.place_order(req()).status is OrderStatus.FILLED  # safe to retry


def test_lost_response_executes_and_reconciles() -> None:
    faults = FaultInjector(lose_next_response=True)
    broker = replay(faults=faults)
    with pytest.raises(OrderOutcomeUnknownError, match="WAS executed"):
        broker.place_order(req())
    found = broker.find_order_by_client_id("c1")
    assert found is not None
    assert found.status is OrderStatus.FILLED
    assert broker.place_order(req()) == found  # retry never duplicates
    assert len(broker.get_positions()) == 1
    assert broker.get_account().balance == D("9996.50")
