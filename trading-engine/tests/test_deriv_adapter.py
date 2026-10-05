"""Deriv adapter against the in-memory Deriv imitation (tests/fake_deriv.py).

These tests prove the translation between the 2kFX broker contract and Deriv
multipliers. They do NOT prove anything about Deriv's live servers — that
requires a real App ID and token (see docs/BROKERS.md).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxrobot.broker_engine.adapters.deriv import DerivAdapter
from fxrobot.broker_engine.adapters.deriv_client import DerivRest
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    MarketClosedError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.models import DealEntry, OrderHint, OrderRequest
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import OrderStatus, OrderType
from tests.fake_deriv import ACCOUNT_ID, APP_ID, TOKEN, FakeDeriv


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


def buy(adapter: DerivAdapter, cid: str = "c" * 24, **kw: object) -> object:
    request = OrderRequest(
        client_order_id=cid,
        symbol=str(kw.pop("symbol", "frxEURUSD")),
        side=kw.pop("side", Side.BUY),  # type: ignore[arg-type]
        order_type=kw.pop("order_type", OrderType.MARKET),  # type: ignore[arg-type]
        volume=Decimal(str(kw.pop("volume", "0.01"))),
        stop_loss=kw.pop("stop_loss", Decimal("1.09500")),  # type: ignore[arg-type]
        take_profit=kw.pop("take_profit", Decimal("1.11000")),  # type: ignore[arg-type]
        price=kw.pop("price", None),  # type: ignore[arg-type]
    )
    return adapter.place_order(request)


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


def test_get_symbol_uses_lowest_multiplier_and_stake_limits(deriv: DerivAdapter) -> None:
    info = deriv.get_symbol("EURUSD")  # canonical names resolve to frxEURUSD
    assert info.name == "frxEURUSD"
    assert deriv.multiplier_for("frxEURUSD") == 100
    # stake 1..2000 USD at x100; 1 lot = 100 000 EUR = 110 000 USD → 0.01..1.81 lots
    assert info.volume_min == Decimal("0.01")
    assert info.volume_max == Decimal("1.81")
    assert info.contract_size == 100_000
    assert deriv.get_symbol("R_100").contract_size == 1


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


# ── trading ──────────────────────────────────────────────────────────────


def test_market_buy_converts_prices_to_deriv_amounts(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv, volume="0.01")  # 1000 EUR ≈ 1100 USD notional → stake 11.00 at x100
    assert result.status is OrderStatus.FILLED  # type: ignore[attr-defined]
    proposal = next(
        r
        for r in fake.requests
        if "proposal" in r and "proposal_open_contract" not in r and "limit_order" in r
    )
    assert proposal["contract_type"] == "MULTUP" and proposal["multiplier"] == 100
    assert proposal["amount"] == 11.0
    # stop 50 pips away on 1100 notional: 1100 * 0.0050 / 1.1 = 5.00 USD
    assert proposal["limit_order"] == {"stop_loss": 5.0, "take_profit": 10.0}
    contract = fake.contracts[int(result.broker_position_id)]  # type: ignore[attr-defined]
    assert contract.stake == Decimal("11")
    assert result.filled_volume == Decimal("0.0100")  # type: ignore[attr-defined]
    assert result.fill_price == Decimal("1.1")  # type: ignore[attr-defined]
    positions = deriv.get_positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.side is Side.BUY and position.volume == Decimal("0.0100")
    assert position.stop_loss == Decimal("1.095") and position.take_profit == Decimal("1.11")
    assert position.client_order_id == "c" * 24
    assert deriv.get_account().balance == Decimal("9989")


def test_sell_is_multdown(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    buy(deriv, side=Side.SELL, stop_loss=Decimal("1.10500"), take_profit=Decimal("1.09000"))
    assert next(iter(fake.contracts.values())).contract_type == "MULTDOWN"
    assert deriv.get_positions()[0].side is Side.SELL


def test_stop_beyond_the_stake_is_refused_before_sending(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    with pytest.raises(OrderRejectedError, match="Stop loss is too far"):
        buy(deriv, stop_loss=Decimal("1.08000"))  # 1.8% move > 1% allowed at x100
    assert not fake.contracts


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
    assert result.status is OrderStatus.FILLED  # type: ignore[attr-defined]


def test_close_position_sells_at_market_and_reports_the_deal(
    deriv: DerivAdapter, fake: FakeDeriv
) -> None:
    result = buy(deriv)
    position_id = result.broker_position_id  # type: ignore[attr-defined]
    fake.set_price("frxEURUSD", "1.10220")  # +0.2% → +2.20
    closed = deriv.close_position(position_id, "d" * 24)
    assert closed.status is OrderStatus.FILLED
    assert closed.fill_price == Decimal("1.1022")
    assert deriv.get_positions() == []
    deals = deriv.get_deals(
        datetime.fromtimestamp(fake.now, UTC) - timedelta(days=1),
        datetime.fromtimestamp(fake.now, UTC) + timedelta(minutes=5),
    )
    exits = [d for d in deals if d.entry is DealEntry.OUT]
    assert len(exits) == 1 and exits[0].profit == Decimal("2.20")
    assert exits[0].position_id == position_id


def test_partial_close_is_refused(deriv: DerivAdapter) -> None:
    result = buy(deriv)
    with pytest.raises(OrderRejectedError, match="partially"):
        deriv.close_position(result.broker_position_id, "e" * 24, Decimal("0.005"))  # type: ignore[attr-defined]


def test_modify_converts_levels_to_amounts(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv)
    position_id = result.broker_position_id  # type: ignore[attr-defined]
    deriv.modify_position(position_id, Decimal("1.09780"), Decimal("1.11500"))
    contract = fake.contracts[int(position_id)]
    assert contract.stop_amount == Decimal("2.2")  # 0.2% of 1100
    assert contract.take_amount == Decimal("15")
    with pytest.raises(OrderRejectedError, match="losing side"):
        deriv.modify_position(position_id, Decimal("1.12"), None)


def test_stop_loss_hit_at_broker_shows_as_sl_deal(deriv: DerivAdapter, fake: FakeDeriv) -> None:
    result = buy(deriv)
    fake.close_externally(int(result.broker_position_id))  # type: ignore[attr-defined]
    deriv._portfolio_at = 0  # type: ignore[attr-defined]
    assert deriv.get_positions() == []
    deals = deriv.get_deals(
        datetime.fromtimestamp(fake.now, UTC) - timedelta(days=1),
        datetime.fromtimestamp(fake.now, UTC) + timedelta(minutes=5),
    )
    exit_deal = next(d for d in deals if d.entry is DealEntry.OUT)
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
    buys = [r for r in fake.requests if "buy" in r]
    assert len(buys) == 1
    # A restarted engine has no memory of the intent: it matches by hint.
    fresh = make(fake)
    fresh.connect()
    found = fresh.find_order_by_client_id(
        "f" * 24, OrderHint("frxEURUSD", Side.BUY, Decimal("0.01"), sent_at)
    )
    assert found is not None and found.status is OrderStatus.FILLED
    assert found.broker_position_id == str(next(iter(fake.contracts)))
    assert len([r for r in fake.requests if "buy" in r]) == 1  # never re-sent
    # The matched contract is now tied to our order id.
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
    assert (
        deriv.find_order_by_client_id(
            "h" * 24, OrderHint("frxEURUSD", Side.BUY, Decimal(1), long_ago)
        )
        is None
    )
    now = datetime.fromtimestamp(fake.now, UTC)
    assert (
        deriv.find_order_by_client_id("h" * 24, OrderHint("R_100", Side.BUY, Decimal(1), now))
        is None
    )
    # an already-claimed contract is never handed to a second order
    assert (
        deriv.find_order_by_client_id("h" * 24, OrderHint("frxEURUSD", Side.BUY, Decimal(1), now))
        is None
    )
