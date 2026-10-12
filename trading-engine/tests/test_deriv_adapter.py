"""Deriv adapter against the in-memory Deriv imitation (tests/fake_deriv.py).

These tests prove the translation between the 2kPilot broker contract and Deriv
Options contracts (Rise/Fall and Multipliers, stake-sized). They do NOT prove
anything about Deriv's live servers — that
requires a real App ID and token (see docs/BROKERS.md).
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxrobot.broker_engine.adapters.deriv import DerivAdapter
from fxrobot.broker_engine.adapters.deriv_client import DerivRest, RateLimiter
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerError,
    BrokerRateLimitError,
    MarketClosedError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.models import DealEntry, OrderHint, OrderRequest, OrderResult
from fxrobot.domain.contracts import (
    ContractFamily,
    ContractOrder,
    ContractSpec,
    ContractType,
)
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import OrderStatus, OrderType
from tests.fake_deriv import ACCOUNT_ID, APP_ID, TOKEN, FakeDeriv, FakeSocket


def make(fake: FakeDeriv, *, token: str = TOKEN, account_id: str = ACCOUNT_ID) -> DerivAdapter:
    rest = DerivRest(token=token, app_id=APP_ID, transport=fake.transport())
    return DerivAdapter(
        token=token,
        app_id=APP_ID,
        account_id=account_id,
        rest=rest,
        connector=fake.connector,
        clock=lambda: datetime.fromtimestamp(fake.now, UTC),
    )


@pytest.fixture
def fake() -> FakeDeriv:
    return FakeDeriv()


@pytest.fixture
def deriv(fake: FakeDeriv) -> DerivAdapter:
    adapter = make(fake)
    adapter.connect()
    yield adapter  # type: ignore[misc]
    adapter.disconnect()


def multiplier(
    side: Side = Side.BUY, stake: str = "11", mult: int = 100, **kw: object
) -> ContractOrder:
    spec = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=mult, **kw)  # type: ignore[arg-type]
    return ContractOrder.build(spec, side, Decimal(stake))


def rise_fall(
    side: Side = Side.BUY,
    stake: str = "1",
    duration: int = 5,
    unit: str = "m",
    equals: bool = False,
) -> ContractOrder:
    spec = ContractSpec(
        contract_family=ContractFamily.RISE_FALL,
        duration=duration,
        duration_unit=unit,
        allow_equals=equals,
    )
    return ContractOrder.build(spec, side, Decimal(stake))


def buy(adapter: DerivAdapter, cid: str = "c" * 24, **kw: object) -> OrderResult:
    side = kw.pop("side", Side.BUY)
    contract = kw.pop("contract", None) or multiplier(side)  # type: ignore[arg-type]
    request = OrderRequest(
        client_order_id=cid,
        symbol=str(kw.pop("symbol", "frxEURUSD")),
        side=side,  # type: ignore[arg-type]
        order_type=kw.pop("order_type", OrderType.MARKET),  # type: ignore[arg-type]
        volume=Decimal(1),
        stop_loss=kw.pop("stop_loss", Decimal("1.09500")),  # type: ignore[arg-type]
        take_profit=kw.pop("take_profit", Decimal("1.11000")),  # type: ignore[arg-type]
        price=kw.pop("price", None),  # type: ignore[arg-type]
        contract=contract,  # type: ignore[arg-type]
    )
    return adapter.place_order(request)


def buy_rf(adapter: DerivAdapter, cid: str = "r" * 24, **kw: object) -> OrderResult:
    contract = kw.pop("contract", None) or rise_fall(kw.pop("side", Side.BUY))  # type: ignore[arg-type]
    request = OrderRequest(
        client_order_id=cid,
        symbol=str(kw.pop("symbol", "R_100")),
        side=contract.contract_type.side,  # type: ignore[union-attr]
        order_type=OrderType.MARKET,
        volume=Decimal(1),
        stop_loss=None,
        take_profit=None,
        contract=contract,  # type: ignore[arg-type]
    )
    return adapter.place_order(request)


def window(fake: FakeDeriv) -> tuple[datetime, datetime]:
    now = datetime.fromtimestamp(fake.now, UTC)
    return now - timedelta(days=1), now + timedelta(minutes=5)


# ── connection & account ─────────────────────────────────────────────────


def test_connect_uses_a_fresh_otp_and_reports_a_demo_account(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    account = deriv.get_account()
    assert fake.otps_issued == 1
    assert account.account_id == ACCOUNT_ID
    assert account.environment is AccountEnvironment.DEMO
    assert account.currency == "USD"
    assert account.balance == Decimal("10000")
    assert account.equity == Decimal("10000")
    assert account.trade_allowed is True
    assert deriv.is_connected and deriv.health().connected


def test_real_account_is_reported_as_live(fake: FakeDeriv) -> None:
    fake.account_type = "real"
    adapter = make(fake)
    assert adapter.connect().environment is AccountEnvironment.LIVE
    adapter.disconnect()


def test_bad_token_is_an_auth_error(fake: FakeDeriv) -> None:
    with pytest.raises(BrokerAuthError):
        make(fake, token="wrong").connect()


def test_pat_without_app_id_is_refused_before_any_request() -> None:
    with pytest.raises(BrokerAuthError, match="App ID"):
        DerivRest(token=TOKEN, app_id="")


def test_unknown_account_is_refused(fake: FakeDeriv) -> None:
    with pytest.raises(BrokerAuthError, match="not available"):
        make(fake, account_id="DOT000").connect()


def test_reconnect_requests_a_new_otp(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    fake.sockets[-1].drop()
    deriv._socket._closed.wait(2)  # type: ignore[union-attr]
    assert not deriv.is_connected
    deriv.connect()
    assert fake.otps_issued == 2 and deriv.is_connected


# ── instruments & prices ─────────────────────────────────────────────────


def test_symbols_are_normalised_with_categories(deriv: DerivAdapter) -> None:
    symbols = {s.name: s for s in deriv.get_symbols()}
    eurusd = symbols["frxEURUSD"]
    assert eurusd.canonical_name == "EURUSD"
    assert (eurusd.base_currency, eurusd.quote_currency) == ("EUR", "USD")
    assert eurusd.category == "forex" and eurusd.digits == 5
    assert eurusd.pip_size == Decimal("0.00010")
    assert symbols["R_100"].category == "synthetic"
    assert symbols["R_100"].quote_currency == "USD"


def test_symbols_are_one_contract_and_carry_market_status(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    info = deriv.get_symbol("EURUSD")  # canonical names resolve to frxEURUSD
    assert info.name == "frxEURUSD"
    assert info.volume_min == info.volume_max == Decimal(1)  # one contract, no lots
    assert info.market_open is True and info.trade_allowed is True
    fake.suspended.add("R_100")
    deriv._active_at = 0  # type: ignore[attr-defined]
    r100 = deriv.get_symbol("R_100")
    assert r100.trade_allowed is False and r100.market_open is False
    # active_symbols is no longer limited to multiplier symbols
    request = next(r for r in fake.requests if "active_symbols" in r)
    assert "contract_type" not in request


def test_contract_capabilities_parse_contracts_for(deriv: DerivAdapter) -> None:
    caps = deriv.contract_capabilities("R_100")
    assert caps.rise_fall and caps.allow_equals
    assert {(r.minimum, r.maximum) for r in caps.durations} == {("1t", "10t"), ("15s", "1d")}
    assert caps.multipliers == (40, 100, 200, 300, 400)
    assert caps.spot is False
    # Higher/Lower (CALL with a barrier, 1d–365d) is not treated as Rise/Fall
    assert all(r.maximum != "365d" for r in caps.durations)
    spec = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=5, duration_unit="m")
    assert caps.check(spec) is None
    long = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=2, duration_unit="d")
    assert "not offered" in (caps.check(long) or "")
    ticks = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=11, duration_unit="t")
    assert "1t–10t" in (caps.check(ticks) or "")
    eur = deriv.contract_capabilities("frxEURUSD")
    assert not eur.rise_fall and "Rise/Fall contracts are not offered" in (eur.check(spec) or "")
    assert eur.check(ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=50))


def test_contract_capabilities_read_the_current_contracts_for_shape(deriv: DerivAdapter) -> None:
    """Deriv's current Options API (2026-10, Volatility indices) lists one CALL/PUT
    row per expiry with `barriers: 1` and no `barrier_category` — still Rise/Fall."""
    rows = [
        {
            "contract_category": "callput",
            "contract_type": t,
            "expiry_type": expiry,
            "barriers": 1,
            "min_contract_duration": lo,
            "max_contract_duration": hi,
        }
        for t in ("CALL", "PUT", "CALLE", "PUTE")
        for expiry, lo, hi in (
            ("daily", "1d", "365d"),
            ("intraday", "15s", "1d"),
            ("tick", "1t", "10t"),
        )
    ] + [
        {"contract_category": "multiplier", "contract_type": t, "multiplier_range": [50, 100]}
        for t in ("MULTUP", "MULTDOWN")
    ]
    deriv.resolve("R_100")
    deriv._offered["R_100"] = (rows, time.monotonic())  # pyright: ignore[reportPrivateUsage]
    caps = deriv.contract_capabilities("R_100")
    assert caps.rise_fall and caps.allow_equals
    assert {(r.minimum, r.maximum) for r in caps.durations} == {
        ("1d", "365d"),
        ("15s", "1d"),
        ("1t", "10t"),
    }
    assert (
        caps.check(
            ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=5, duration_unit="m")
        )
        is None
    )
    assert caps.multipliers == (50, 100)

    # Rows explicitly marked as Higher/Lower are never read as Rise/Fall.
    deriv._offered["R_100"] = (
        [{**r, "barrier_category": "euro_non_atm"} for r in rows],
        time.monotonic(),
    )  # pyright: ignore[reportPrivateUsage]
    assert not deriv.contract_capabilities("R_100").rise_fall


def test_quote_contract_reads_stake_limits_from_the_proposal(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    quote = deriv.quote_contract("R_100", rise_fall())
    assert (quote.stake_min, quote.stake_max) == (Decimal("0.35"), Decimal("50000.00"))
    assert quote.payout == Decimal("1.95")
    assert not fake.contracts  # pricing never buys
    fake.stake_limits = False
    missing = deriv.quote_contract("R_100", rise_fall())
    assert missing.stake_min is None and "validation_params" in missing.detail


def test_unknown_symbol_is_unavailable(deriv: DerivAdapter) -> None:
    with pytest.raises(SymbolUnavailableError):
        deriv.get_symbol("XAUUSD")


def test_quote_and_closed_market(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    quote = deriv.get_quote("frxEURUSD")
    assert quote.bid == quote.ask == Decimal("1.1")
    fake.market_closed.add("R_100")
    with pytest.raises(MarketClosedError):
        deriv.get_quote("R_100")


def test_streamed_ticks_update_quotes(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    deriv.get_quote("frxEURUSD")
    fake.set_price("frxEURUSD", "1.10500")
    fake.sockets[-1].push_tick("frxEURUSD")
    deadline = datetime.now(UTC) + timedelta(seconds=2)
    while deriv.get_quote("frxEURUSD").bid != Decimal("1.105") and datetime.now(UTC) < deadline:
        pass
    assert deriv.get_quote("frxEURUSD").bid == Decimal("1.105")


def test_candles_are_closed_bars_only(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    now = datetime.fromtimestamp(fake.now, UTC)
    bars = deriv.get_candles("frxEURUSD", Timeframe.H1, now - timedelta(hours=10), now)
    assert bars and all(b.time + Timeframe.H1.delta <= now for b in bars)
    assert [b.time for b in bars] == sorted(b.time for b in bars)


def test_candle_history_pages_backwards_like_deriv_serves_it(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    """Deriv ignores `start` and wants `end` as a string: the adapter pages back by `end`."""
    now = datetime.fromtimestamp(fake.now, UTC)
    start = now - timedelta(days=10)  # 2,880 M5 bars: three pages of 1,000
    bars = deriv.get_candles("R_100", Timeframe.M5, start, now)
    requests = [r for r in fake.requests if "ticks_history" in r]
    assert len(requests) >= 3
    assert all(isinstance(r["end"], str) and "start" not in r for r in requests)
    assert all("adjust_start_time" not in r for r in requests)
    times = [b.time for b in bars]
    assert times == sorted(set(times))  # no duplicates across pages
    assert all(b - a == Timeframe.M5.delta for a, b in itertools.pairwise(times))
    assert times[0] >= start and times[-1] + Timeframe.M5.delta <= now
    assert len(bars) >= 2870


def test_candle_history_stops_at_the_server_history_limit(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    """Before its history limit Deriv answers with the LATEST bars: never mixed in."""
    now = datetime.fromtimestamp(fake.now, UTC)
    fake.history_from = fake.now - 3 * 86400
    old_end = now - timedelta(days=20)
    assert deriv.get_candles("R_100", Timeframe.M5, now - timedelta(days=30), old_end) == []
    bars = deriv.get_candles("R_100", Timeframe.M5, now - timedelta(days=30), now)
    assert bars[0].time >= datetime.fromtimestamp(fake.history_from, UTC)


# ── Rise/Fall ────────────────────────────────────────────────────────────


def test_rise_fall_buy_uses_proposal_then_buy_at_ask(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy_rf(deriv)
    proposal = next(r for r in fake.requests if r.get("contract_type") == "CALL")
    assert {k: proposal[k] for k in ("underlying_symbol", "basis", "amount", "currency")} == {
        "underlying_symbol": "R_100",
        "basis": "stake",
        "amount": 1.0,
        "currency": "USD",
    }
    assert (proposal["duration"], proposal["duration_unit"]) == (5, "m")
    assert "symbol" not in proposal and "multiplier" not in proposal
    purchase = next(r for r in fake.requests if "buy" in r)
    assert purchase["price"] == 1.0  # no more than the ask price
    fill = result.contract
    assert fill is not None and fill.contract_type is ContractType.CALL
    assert fill.buy_price == Decimal("1") and fill.payout == Decimal("1.95")
    assert fill.contract_id == result.broker_position_id
    assert fill.transaction_id and fill.longcode and "higher" in fill.longcode
    assert fill.entry_spot == Decimal("637.4")
    assert fill.expires_at == datetime.fromtimestamp(fake.now + 300, UTC)
    position = deriv.get_positions()[0]
    assert position.contract_type is ContractType.CALL and position.stake == Decimal("1.00")
    assert position.payout == Decimal("1.95") and position.volume == 1


def test_allow_equals_buys_calle_and_sell_buys_put(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    buy_rf(deriv, contract=rise_fall(equals=True))
    buy_rf(deriv, cid="s" * 24, contract=rise_fall(Side.SELL))
    types = sorted(c.contract_type for c in fake.contracts.values())
    assert types == ["CALLE", "PUT"]


def test_ask_above_the_stake_is_refused(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    fake.ask_markup = Decimal("0.05")
    with pytest.raises(OrderRejectedError, match="never pays more than the stake"):
        buy_rf(deriv)
    assert not fake.contracts and not [r for r in fake.requests if "buy" in r]


def test_unsupported_duration_is_refused_before_pricing(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    with pytest.raises(OrderRejectedError, match="not offered"):
        buy_rf(deriv, contract=rise_fall(duration=3, unit="d"))
    assert not [r for r in fake.requests if r.get("contract_type") == "CALL"]


def test_rise_fall_settles_won_and_lost_from_string_money_fields(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    won = buy_rf(deriv)
    lost = buy_rf(deriv, cid="t" * 24)
    fake.expire(int(won.broker_position_id or 0), "640.00")
    fake.expire(int(lost.broker_position_id or 0), "637.40")  # equal: CALL loses
    deriv._portfolio_at = 0  # type: ignore[attr-defined]
    assert deriv.get_positions() == []
    deals = {d.position_id: d for d in deriv.get_deals(*window(fake)) if d.entry is DealEntry.OUT}
    win, loss = deals[won.broker_position_id], deals[lost.broker_position_id]
    assert (win.outcome, win.profit, win.reason) == ("WON", Decimal("0.95"), "EXPIRY")
    assert win.payout == Decimal("1.95") and win.price == Decimal("640.00")
    assert (loss.outcome, loss.profit) == ("LOST", Decimal("-1.00"))
    assert loss.contract_type == "CALL"


def test_rise_fall_early_close_only_when_valid_to_sell(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    result = buy_rf(deriv)
    contract = fake.contracts[int(result.broker_position_id or 0)]
    contract.valid_to_sell = False
    with pytest.raises(OrderRejectedError, match="settles at expiry"):
        deriv.close_position(result.broker_position_id or "", "u" * 24)
    assert not [r for r in fake.requests if "sell" in r]
    contract.valid_to_sell = True
    closed = deriv.close_position(result.broker_position_id or "", "u" * 24)
    assert closed.status is OrderStatus.FILLED
    exit_deal = next(d for d in deriv.get_deals(*window(fake)) if d.entry is DealEntry.OUT)
    assert exit_deal.outcome == "SOLD" and exit_deal.reason == "CLIENT"


def test_rise_fall_has_no_stop_to_modify(deriv: DerivAdapter) -> None:
    result = buy_rf(deriv)
    with pytest.raises(OrderRejectedError, match="Only Multiplier"):
        deriv.modify_position(result.broker_position_id or "", Decimal("600"), None)


def test_settled_while_offline_is_found_by_hint_without_rebuying(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fxrobot.broker_engine.adapters.deriv_client as client

    monkeypatch.setattr(client, "REQUEST_TIMEOUT", 0.3)
    fake.timeout_next_buy = True
    sent_at = datetime.fromtimestamp(fake.now, UTC)
    original = deriv._ws().request

    def quick(payload: dict[str, object], timeout: float = 15) -> dict[str, object]:
        return original(payload, timeout=0.3 if "buy" in payload else timeout)

    monkeypatch.setattr(deriv._ws(), "request", quick)
    with pytest.raises(OrderOutcomeUnknownError):
        buy_rf(deriv, cid="v" * 24)
    cid = next(iter(fake.contracts))
    fake.expire(cid, "630")  # expired (lost) while we were away
    fresh = make(fake)
    fresh.connect()
    hint = OrderHint("R_100", Side.BUY, Decimal(1), sent_at, contract_type=ContractType.CALL)
    found = fresh.find_order_by_client_id("v" * 24, hint)
    assert found is not None and found.broker_position_id == str(cid)
    assert found.contract is not None and found.contract.buy_price == Decimal("1.00")
    assert len([r for r in fake.requests if "buy" in r]) == 1  # never re-bought
    # a PUT hint does not claim a CALL contract
    other = OrderHint("R_100", Side.SELL, Decimal(1), sent_at, contract_type=ContractType.PUT)
    assert fresh.find_order_by_client_id("w" * 24, other) is None
    fresh.disconnect()


def test_rate_limiter_refuses_before_sending() -> None:
    clock = [0.0]
    limiter = RateLimiter(
        {"trading": ((60.0, 2),), "other": ((60.0, 100),)},
        clock=lambda: clock[0],
        sleep=lambda s: clock.__setitem__(0, clock[0] + s),
        max_wait=1.0,
    )
    limiter.acquire("trading")
    limiter.acquire("trading")

    with pytest.raises(BrokerRateLimitError, match="nothing was sent"):
        limiter.acquire("trading")
    clock[0] = 59.5  # the oldest request leaves the window within max_wait
    limiter.acquire("trading")
    limiter.acquire(None)  # ping is never counted


def test_rate_limited_buy_is_a_rejection(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    deriv._limiter = RateLimiter(  # type: ignore[attr-defined]
        {
            "trading": ((60.0, 1),),
            "other": ((60.0, 1000),),
            "account": ((60.0, 1000),),
            "history": ((60.0, 1000),),
        },
        max_wait=0,
    )
    deriv._socket._limiter = deriv._limiter  # type: ignore[union-attr, attr-defined]
    with pytest.raises(OrderRejectedError, match="budget"):
        buy_rf(deriv)  # proposal uses the budget; the buy is refused before sending
    assert not fake.contracts


# ── Multipliers ──────────────────────────────────────────────────────────


def test_multiplier_buy_uses_stake_and_converts_prices_to_amounts(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    result = buy(deriv)  # stake 11 at ×100 → notional 1100
    proposal = next(
        r
        for r in fake.requests
        if "proposal" in r and "proposal_open_contract" not in r and "limit_order" in r
    )
    assert proposal["contract_type"] == "MULTUP" and proposal["multiplier"] == 100
    assert proposal["amount"] == 11.0 and proposal["basis"] == "stake"
    # stop 50 pips away on 1100 notional: 1100 * 0.0050 / 1.1 = 5.00 USD
    assert proposal["limit_order"] == {"stop_loss": 5.0, "take_profit": 10.0}
    assert fake.contracts[int(result.broker_position_id or 0)].stake == Decimal("11")
    assert result.filled_volume == 1 and result.fill_price == Decimal("1.1")
    assert result.contract is not None and result.contract.multiplier == 100
    position = deriv.get_positions()[0]
    assert position.side is Side.BUY and position.contract_type is ContractType.MULTUP
    assert position.stop_loss == Decimal("1.095") and position.take_profit == Decimal("1.11")
    assert position.client_order_id == "c" * 24
    assert deriv.get_account().balance == Decimal("9989")


def test_explicit_money_amounts_win_over_strategy_prices(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    buy(
        deriv,
        contract=multiplier(take_profit_amount=Decimal("3"), stop_loss_amount=Decimal("2")),
    )
    proposal = next(r for r in fake.requests if "limit_order" in r)
    assert proposal["limit_order"] == {"stop_loss": 2.0, "take_profit": 3.0}


def test_strategy_stop_beyond_the_stake_is_left_to_the_stop_out(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    buy(deriv, stop_loss=Decimal("1.08000"))  # 1.8% move > the 1% stop out at ×100
    proposal = next(r for r in fake.requests if "limit_order" in r)
    assert "stop_loss" not in proposal["limit_order"]  # Deriv's stop out caps the loss


def test_multiplier_not_offered_is_refused(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    with pytest.raises(OrderRejectedError, match="not offered"):
        buy(deriv, contract=multiplier(mult=7))
    assert not fake.contracts


def test_lots_are_refused(deriv: DerivAdapter) -> None:
    request = OrderRequest(
        "x" * 24, "frxEURUSD", Side.BUY, OrderType.MARKET, Decimal("0.01"), Decimal("1.095"), None
    )
    with pytest.raises(OrderRejectedError, match="Rise/Fall or Multiplier"):
        deriv.place_order(request)


def test_sell_is_multdown(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    buy(deriv, side=Side.SELL, stop_loss=Decimal("1.10500"), take_profit=Decimal("1.09000"))
    assert next(iter(fake.contracts.values())).contract_type == "MULTDOWN"
    assert deriv.get_positions()[0].side is Side.SELL


def test_pending_orders_are_not_offered(deriv: DerivAdapter) -> None:
    assert deriv.capabilities.pending_orders is False
    with pytest.raises(OrderRejectedError, match="pending"):
        buy(deriv, order_type=OrderType.LIMIT, price=Decimal("1.09"))
    assert deriv.get_orders() == []


def test_closed_market_rejects_the_order(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    deriv.get_symbol("frxEURUSD")
    fake.market_closed.add("frxEURUSD")
    with pytest.raises(OrderRejectedError):
        buy(deriv)
    assert not fake.contracts


def test_equity_includes_open_contract_value(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv)
    fake.set_price("frxEURUSD", "1.10550")  # +0.5% → +5.50 on 1100 notional
    deriv._contracts.clear()  # type: ignore[attr-defined]
    deriv._portfolio_at = 0  # type: ignore[attr-defined]
    position = deriv.get_positions()[0]
    assert position.unrealized_pnl == Decimal("5.5")
    account = deriv.get_account()
    assert account.equity == account.balance + Decimal("16.5")
    assert result.status is OrderStatus.FILLED


def test_close_position_sells_at_market_and_reports_the_deal(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    result = buy(deriv)
    position_id = result.broker_position_id or ""
    fake.set_price("frxEURUSD", "1.10220")  # +0.2% → +2.20
    closed = deriv.close_position(position_id, "d" * 24)
    assert closed.status is OrderStatus.FILLED
    assert closed.fill_price == Decimal("1.1022")
    assert deriv.get_positions() == []
    exits = [d for d in deriv.get_deals(*window(fake)) if d.entry is DealEntry.OUT]
    assert len(exits) == 1 and exits[0].profit == Decimal("2.20")
    assert exits[0].position_id == position_id and exits[0].outcome == "SOLD"


def test_partial_close_is_refused(deriv: DerivAdapter) -> None:
    result = buy(deriv)
    with pytest.raises(OrderRejectedError, match="partially"):
        deriv.close_position(result.broker_position_id or "", "e" * 24, Decimal("0.5"))


def test_modify_converts_levels_to_amounts(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv)
    position_id = result.broker_position_id or ""
    deriv.modify_position(position_id, Decimal("1.09780"), Decimal("1.11500"))
    contract = fake.contracts[int(position_id)]
    assert contract.stop_amount == Decimal("2.2")  # 0.2% of 1100
    assert contract.take_amount == Decimal("15")
    with pytest.raises(OrderRejectedError, match="losing side"):
        deriv.modify_position(position_id, Decimal("1.12"), None)


def test_stop_loss_hit_at_broker_shows_as_sl_deal(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv)
    fake.close_externally(int(result.broker_position_id or 0))
    deriv._portfolio_at = 0  # type: ignore[attr-defined]
    assert deriv.get_positions() == []
    exit_deal = next(d for d in deriv.get_deals(*window(fake)) if d.entry is DealEntry.OUT)
    assert exit_deal.reason == "SL" and exit_deal.profit == Decimal("-5.00")


# ── idempotency & uncertain outcomes ─────────────────────────────────────


def test_buy_timeout_is_unknown_and_reconciles_without_resending(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fxrobot.broker_engine.adapters.deriv_client as client

    monkeypatch.setattr(client, "REQUEST_TIMEOUT", 0.3)
    fake.timeout_next_buy = True
    sent_at = datetime.fromtimestamp(fake.now, UTC)
    original = deriv._ws().request  # shorter wait for the buy only

    def quick(payload: dict[str, object], timeout: float = 15) -> dict[str, object]:
        return original(payload, timeout=0.3 if "buy" in payload else timeout)

    monkeypatch.setattr(deriv._ws(), "request", quick)
    with pytest.raises(OrderOutcomeUnknownError):
        buy(deriv, cid="f" * 24)
    assert len([r for r in fake.requests if "buy" in r]) == 1
    # A restarted engine has no memory of the intent: it matches by hint.
    fresh = make(fake)
    fresh.connect()
    found = fresh.find_order_by_client_id(
        "f" * 24,
        OrderHint("frxEURUSD", Side.BUY, Decimal(1), sent_at, contract_type=ContractType.MULTUP),
    )
    assert found is not None and found.status is OrderStatus.FILLED
    assert found.broker_position_id == str(next(iter(fake.contracts)))
    assert len([r for r in fake.requests if "buy" in r]) == 1  # never re-sent
    assert fresh.get_positions()[0].client_order_id == "f" * 24
    fresh.disconnect()


def test_link_drop_after_buy_is_unknown(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    fake.drop_after_buy = True
    with pytest.raises(OrderOutcomeUnknownError):
        buy(deriv)
    assert len(fake.contracts) == 1  # it did execute; reconciliation will find it


def test_hint_does_not_match_other_symbols_or_old_contracts(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    buy(deriv, cid="g" * 24)
    long_ago = datetime.fromtimestamp(fake.now, UTC) - timedelta(hours=2)
    up = ContractType.MULTUP
    assert (
        deriv.find_order_by_client_id(
            "h" * 24, OrderHint("frxEURUSD", Side.BUY, Decimal(1), long_ago, contract_type=up)
        )
        is None
    )
    now = datetime.fromtimestamp(fake.now, UTC)
    assert (
        deriv.find_order_by_client_id(
            "h" * 24, OrderHint("R_100", Side.BUY, Decimal(1), now, contract_type=up)
        )
        is None
    )
    # an already-claimed contract is never handed to a second order
    assert (
        deriv.find_order_by_client_id(
            "h" * 24, OrderHint("frxEURUSD", Side.BUY, Decimal(1), now, contract_type=up)
        )
        is None
    )


def _drop_link_after_reply(monkeypatch: pytest.MonkeyPatch, request_key: str) -> None:
    """Deriv answers `request_key`, then the link dies before anything else."""
    original = FakeSocket.send

    def send(self: FakeSocket, message: str) -> None:
        original(self, message)
        if request_key in json.loads(message):
            self.drop()  # the reply is already queued

    monkeypatch.setattr(FakeSocket, "send", send)


def test_link_drop_after_the_buy_receipt_is_still_a_fill(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deriv acknowledged the buy: a failed detail fetch must not report "not sent"."""
    _drop_link_after_reply(monkeypatch, "buy")
    result = buy(deriv, cid="a" * 24)
    (contract_id,) = fake.contracts
    assert result.status is OrderStatus.FILLED
    assert result.broker_position_id == str(contract_id)
    assert result.contract is not None
    assert result.contract.buy_price == Decimal("11")  # from the receipt
    assert result.contract.start_time == datetime.fromtimestamp(fake.now, UTC)


def test_link_drop_after_the_sell_receipt_is_still_a_sale(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = buy(deriv)
    _drop_link_after_reply(monkeypatch, "sell")
    closed = deriv.close_position(result.broker_position_id or "", "s" * 24)
    assert closed.status is OrderStatus.FILLED
    assert fake.contracts[int(result.broker_position_id or 0)].sold


def _timed_out_rise_fall(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch, cid: str
) -> None:
    import fxrobot.broker_engine.adapters.deriv_client as client

    monkeypatch.setattr(client, "REQUEST_TIMEOUT", 0.3)
    fake.timeout_next_buy = True
    original = deriv._ws().request

    def quick(payload: dict[str, object], timeout: float = 15) -> dict[str, object]:
        return original(payload, timeout=0.3 if "buy" in payload else timeout)

    monkeypatch.setattr(deriv._ws(), "request", quick)
    with pytest.raises(OrderOutcomeUnknownError):
        buy_rf(deriv, cid=cid)


def test_history_failure_keeps_an_uncertain_order_unknown(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concluding "not executed" needs BOTH portfolio and profit_table to be read."""
    sent_at = datetime.fromtimestamp(fake.now, UTC)
    _timed_out_rise_fall(deriv, fake, monkeypatch, "z" * 24)
    (contract_id,) = fake.contracts
    fake.expire(contract_id, "700")  # settled before we reconcile
    fresh = make(fake)
    fresh.connect()

    def limited(*args: object, **kwargs: object) -> object:
        raise BrokerRateLimitError("history budget used up")

    hint = OrderHint("R_100", Side.BUY, Decimal(1), sent_at, contract_type=ContractType.CALL)
    with monkeypatch.context() as patch:
        patch.setattr(fresh, "get_deals", limited)
        with pytest.raises(BrokerError):
            fresh.find_order_by_client_id("z" * 24, hint)
    found = fresh.find_order_by_client_id("z" * 24, hint)  # history readable again
    assert found is not None and found.broker_position_id == str(contract_id)
    fresh.disconnect()


def test_contract_claimed_in_the_database_is_never_matched_after_restart(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    """The adapter's in-memory claims are lost on restart; the database's are not."""
    claimed = buy(deriv, cid="a" * 24)
    deriv.disconnect()
    fresh = make(fake)
    fresh.connect()
    now = datetime.fromtimestamp(fake.now, UTC)
    up = ContractType.MULTUP
    hint = OrderHint(
        "frxEURUSD",
        Side.BUY,
        Decimal(1),
        now,
        contract_type=up,
        claimed_ids=frozenset({claimed.broker_position_id or ""}),
    )
    assert fresh.find_order_by_client_id("b" * 24, hint) is None
    fresh.disconnect()


def test_reconciliation_prefers_the_contract_that_fits_the_order(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    earlier = buy(deriv, cid="a" * 24, contract=multiplier(stake="12"))
    fake.now += 2
    ours = buy(deriv, cid="b" * 24, contract=multiplier(stake="11"))
    deriv.disconnect()
    fresh = make(fake)
    fresh.connect()
    sent_at = datetime.fromtimestamp(fake.now, UTC)
    hint = OrderHint("frxEURUSD", Side.BUY, Decimal(1), sent_at, contract_type=ContractType.MULTUP)
    with_stake = dataclasses.replace(hint, stake=Decimal("11.00"))
    found = fresh.find_order_by_client_id("c" * 24, with_stake)
    assert found is not None and found.broker_position_id == ours.broker_position_id
    # Without a stake the closest purchase time wins (not simply the oldest contract).
    found = fresh.find_order_by_client_id("d" * 24, hint)
    assert found is not None and found.broker_position_id == earlier.broker_position_id
    fresh.disconnect()


def test_uncertain_orders_share_one_portfolio_and_history_read(fake: FakeDeriv) -> None:
    """Deriv allows ~30 portfolio + profit_table calls a minute: one pass, one read."""
    adapter = make(fake)
    adapter.connect()
    now = datetime.fromtimestamp(fake.now, UTC)

    def calls(kind: str) -> int:
        return len([r for r in fake.requests if kind in r])

    before = calls("portfolio"), calls("profit_table")
    for i in range(3):
        hint = OrderHint(
            "R_100",
            Side.BUY,
            Decimal(1),
            now - timedelta(seconds=i),
            contract_type=ContractType.CALL,
        )
        assert adapter.find_order_by_client_id(str(i) * 24, hint) is None
    assert calls("portfolio") - before[0] <= 1
    assert calls("profit_table") - before[1] == 1
    adapter.disconnect()


def test_rate_limited_contract_details_fail_the_history_read(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never a deal with entry/exit 0 or a guessed exit reason: retry later instead."""
    result = buy(deriv)
    fake.close_externally(int(result.broker_position_id or 0))
    fresh = make(fake)
    fresh.connect()
    original = fresh._ws().request

    def limited(payload: dict[str, object], timeout: float = 15) -> dict[str, object]:
        if "proposal_open_contract" in payload and "contract_id" in payload:
            raise BrokerRateLimitError("budget used up")
        return original(payload, timeout=timeout)

    with monkeypatch.context() as patch:
        patch.setattr(fresh._ws(), "request", limited)
        with pytest.raises(BrokerError, match="history unavailable"):
            fresh.get_deals(*window(fake))
    deal = next(d for d in fresh.get_deals(*window(fake)) if d.entry is DealEntry.OUT)
    assert deal.reason == "SL" and deal.outcome == "LOST" and deal.price != 0
    fresh.disconnect()


def test_sold_contract_missing_from_profit_table_is_reported_from_its_details(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """profit_table can lag a sale: the contract's own sold details carry the P/L."""
    result = buy(deriv)
    fake.set_price("frxEURUSD", "1.10220")  # +2.20
    deriv.close_position(result.broker_position_id or "", "d" * 24)
    original = deriv._ws().request

    def lagging(payload: dict[str, object], timeout: float = 15) -> dict[str, object]:
        if "profit_table" in payload:
            return {"profit_table": {"count": 0, "transactions": []}}
        return original(payload, timeout=timeout)

    monkeypatch.setattr(deriv._ws(), "request", lagging)
    exits = [d for d in deriv.get_deals(*window(fake)) if d.entry is DealEntry.OUT]
    assert len(exits) == 1 and exits[0].position_id == result.broker_position_id
    assert exits[0].profit == Decimal("2.20")


def test_a_closed_market_is_rechecked_within_a_minute(
    deriv: DerivAdapter, fake: FakeDeriv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen live (2026-10-12): forex opened at 00:00 UTC but the cached "closed"
    status held for up to 10 minutes, so the first signal arrived too late to trade."""
    import fxrobot.broker_engine.adapters.deriv as deriv_module

    clock = [1000.0]
    monkeypatch.setattr(deriv_module.time, "monotonic", lambda: clock[0])
    fake.market_closed.add("frxEURUSD")
    deriv._active_at = 0.0  # pyright: ignore[reportPrivateUsage]
    assert deriv.get_symbol("EURUSD").market_open is False

    fake.market_closed.clear()  # the market opens
    clock[0] += 30
    assert deriv.get_symbol("EURUSD").market_open is False  # still within the recheck window
    clock[0] += 31
    assert deriv.get_symbol("EURUSD").market_open is True

    # An open market keeps the long cache (no extra requests per tick).
    asked = len(fake.requests)
    clock[0] += 120
    deriv.get_symbol("EURUSD")
    assert len(fake.requests) == asked


def test_a_forgotten_proposal_is_priced_again_and_bought_once(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    """Seen live (2026-10-12, frxUSDJPY): the buy answered InvalidContractProposal
    and the approved trade was lost. Nothing is bought on that answer: re-price."""
    fake.forget_proposals = 1
    result = buy_rf(deriv)
    assert result.contract is not None
    assert len(fake.contracts) == 1
    assert sum(1 for m in fake.requests if "buy" in m) == 2


def test_contracts_are_bought_by_their_parameters_not_a_proposal_id(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    """Deriv's buy schema: `buy: "1"` with `parameters` (underlying_symbol, …)."""
    buy_rf(deriv)
    sent = next(m for m in fake.requests if "buy" in m)
    assert sent["buy"] == "1" and sent["price"] == 1.0
    params = sent["parameters"]
    assert params["underlying_symbol"] == "R_100" and params["contract_type"] == "CALL"
    assert params["basis"] == "stake" and params["amount"] == 1.0 and "duration" in params


def test_a_proposal_forgotten_twice_is_refused(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    fake.forget_proposals = 2
    with pytest.raises(OrderRejectedError, match="InvalidContractProposal"):
        buy_rf(deriv)
    assert not fake.contracts


def test_pricing_reconnects_once_after_a_dropped_link(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    """Seen live (2026-10-12): "Deriv connection lost before the reply" while pricing
    refused the trade. Pricing buys nothing, so reconnect and price again."""
    fake.drop_on_proposal = 1
    quote = deriv.quote_contract("R_100", rise_fall(Side.BUY))
    assert quote.stake_min is not None and deriv.is_connected
