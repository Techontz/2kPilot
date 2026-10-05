"""Contract tests: the backend `MT5BridgeAdapter` against the REAL `mt5_bridge` app.

The bridge app is built exactly as in production, except that the
`MetaTrader5` module is replaced by the bridge's own realistic in-memory fake
(`mt5_bridge/tests/fake_mt5.py`). Requests travel through httpx → the ASGI
app (HMAC middleware, journal, service, mapping) and back, so these tests
verify that both sides agree on paths, signing, JSON shapes and error codes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

pytest.importorskip("mt5_bridge")

from fastapi.testclient import TestClient
from mt5_bridge.app import create_app
from mt5_bridge.config import Settings as BridgeSettings

from fxrobot.broker_engine.adapters.mt5_bridge import (
    MT5BridgeAdapter,
    sign_response,
)
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    InsufficientMarginError,
    InvalidBrokerResponseError,
    MarketClosedError,
    NotFoundError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.models import (
    DealEntry,
    OrderModification,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment

_FAKE_PATH = Path(__file__).resolve().parents[2] / "mt5_bridge" / "tests" / "fake_mt5.py"
if not _FAKE_PATH.exists():  # pragma: no cover - the bridge sources are not checked out
    pytest.skip("mt5_bridge test fake not available", allow_module_level=True)


def _load_fake() -> ModuleType:
    name = "_fxrobot_contract_fake_mt5"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _FAKE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fake_mt5 = _load_fake()

SECRET = "contract-secret-" + "k" * 40
WRONG_SECRET = "wrong-secret-" + "z" * 40
LOGIN, PASSWORD, SERVER = "5012345", "correct-horse", "MetaQuotes-Demo"
# Thursday 2026-10-01 13:00:05 UTC — FX market open.
NOW = datetime(2026, 10, 1, 13, 0, 5, tzinfo=UTC)
SERVER_OFFSET = 3 * 3600
H1 = 16385
COID = "fxcontract0000000000001"


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RewritingTransport(httpx.BaseTransport):
    """Wraps the bridge transport so a test can tamper with responses in flight."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        rewrite: Callable[[httpx.Request, httpx.Response], httpx.Response] | None = None,
    ) -> None:
        self.inner = inner
        self.rewrite = rewrite
        self.fail_with: Exception | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.fail_with is not None:
            raise self.fail_with
        response = self.inner.handle_request(request)
        response.read()
        if self.rewrite is None:
            return response
        return self.rewrite(request, response)


def resign(
    request: httpx.Request, status: int, body: bytes, headers: httpx.Headers
) -> httpx.Response:
    """A response with a VALID signature (as a compromised-but-keyed peer could send)."""
    out = {k: v for k, v in headers.items() if k.lower() not in ("content-length",)}
    out["x-fx-signature"] = sign_response(SECRET, request.headers["X-FX-Nonce"], status, body)
    return httpx.Response(status, headers=out, content=body)


@dataclass
class Env:
    adapter: MT5BridgeAdapter
    fake: Any
    clock: Clock
    transport: RewritingTransport
    client: TestClient

    def make_adapter(self, secret: str = SECRET, **kw: Any) -> MT5BridgeAdapter:
        return MT5BridgeAdapter(
            base_url="http://testserver",
            secret=secret,
            login=kw.pop("login", LOGIN),
            password=kw.pop("password", PASSWORD),
            server=kw.pop("server", SERVER),
            transport=kw.pop("transport", self.transport),
            clock=kw.pop("clock", self.clock),
        )


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    clock = Clock(NOW.timestamp())
    fake = fake_mt5.FakeMT5(clock=clock)
    settings = BridgeSettings(
        _env_file=None,
        bridge_secret=SECRET,
        journal_path=str(tmp_path / "journal.sqlite3"),
        broker_server_utc_offset="+3",
        read_timeout_seconds=2.0,
        trade_timeout_seconds=2.0,
        connect_timeout_seconds=2.0,
    )
    app = create_app(settings, mt5_module=fake, clock=clock)
    with TestClient(app) as client:
        transport = RewritingTransport(client._transport)
        e = Env(adapter=None, fake=fake, clock=clock, transport=transport, client=client)  # type: ignore[arg-type]
        e.adapter = e.make_adapter()
        yield e


@pytest.fixture
def connected(env: Env) -> Env:
    env.adapter.connect()
    return env


def market(
    coid: str = COID,
    side: Side = Side.BUY,
    volume: str = "0.10",
    sl: str | None = "1.08200",
    tp: str | None = "1.09100",
    **kw: Any,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        symbol=kw.pop("symbol", "EURUSD"),
        side=side,
        order_type=kw.pop("order_type", OrderType.MARKET),
        volume=Decimal(volume),
        stop_loss=Decimal(sl) if sl else None,
        take_profit=Decimal(tp) if tp else None,
        **kw,
    )


def server_epoch(moment: datetime) -> int:
    return int(moment.timestamp()) + SERVER_OFFSET


# ── session / account ────────────────────────────────────────────────────────


def test_connect_maps_demo_account(env: Env) -> None:
    account = env.adapter.connect()
    assert env.adapter.is_connected
    assert account.account_id == LOGIN
    assert account.environment is AccountEnvironment.DEMO
    assert account.currency == "USD"
    assert account.server == SERVER
    assert account.balance == Decimal("10000.00")
    assert account.equity == Decimal("10000.00")
    assert account.leverage == 100
    assert account.trade_allowed is True
    assert env.fake.login_calls == [(int(LOGIN), SERVER)]


@pytest.mark.parametrize(
    ("trade_mode", "expected"),
    [
        (0, AccountEnvironment.DEMO),
        (2, AccountEnvironment.LIVE),
        (1, AccountEnvironment.UNKNOWN),  # contest accounts are never assumed to be demo
    ],
)
def test_account_environment_mapping(
    env: Env, trade_mode: int, expected: AccountEnvironment
) -> None:
    env.fake.trade_mode = trade_mode
    assert env.adapter.connect().environment is expected
    assert env.adapter.get_account().environment is expected


def test_bridge_claiming_paper_environment_is_downgraded_to_unknown(env: Env) -> None:
    def rewrite(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path.endswith("/session/connect"):
            payload = response.json()
            payload["environment"] = "PAPER"
            return resign(
                request, response.status_code, json.dumps(payload).encode(), response.headers
            )
        return response

    env.transport.rewrite = rewrite
    # A real broker account can never be PAPER; treating it as such could let
    # paper-mode safety relaxations apply to real money.
    assert env.adapter.connect().environment is AccountEnvironment.UNKNOWN


def test_wrong_password_is_broker_auth_error(env: Env) -> None:
    adapter = env.make_adapter(password="nope-nope")
    with pytest.raises(BrokerAuthError) as info:
        adapter.connect()
    assert info.value.broker_code == "-6"
    assert not adapter.is_connected


def test_terminal_initialise_failure_is_connection_error_not_auth(env: Env) -> None:
    env.fake.initialize_ok = False
    with pytest.raises(BrokerConnectionError) as info:
        env.adapter.connect()
    assert not isinstance(info.value, BrokerAuthError)
    assert not env.adapter.is_connected


def test_terminal_lost_trade_server_marks_adapter_disconnected(connected: Env) -> None:
    connected.fake.connected = False
    with pytest.raises(BrokerConnectionError):
        connected.adapter.get_account()
    assert not connected.adapter.is_connected


def test_health_reports_terminal_and_login(connected: Env) -> None:
    health = connected.adapter.health()
    assert health.connected is True
    assert health.detail == f"MT5 {SERVER}"
    assert health.latency_ms is not None


def test_health_false_when_terminal_offline(connected: Env) -> None:
    connected.fake.connected = False
    health = connected.adapter.health()
    assert health.connected is False
    assert not connected.adapter.is_connected


def test_disconnect_marks_adapter_disconnected(connected: Env) -> None:
    connected.adapter.disconnect()
    assert not connected.adapter.is_connected


def test_repr_never_reveals_credentials(env: Env) -> None:
    text = repr(env.adapter)
    assert PASSWORD not in text
    assert SECRET not in text
    assert LOGIN in text


def test_short_secret_refused() -> None:
    with pytest.raises(ValueError, match="32"):
        MT5BridgeAdapter(base_url="http://x", secret="short", login="1", password="p", server="s")


# ── market data ──────────────────────────────────────────────────────────────


def test_symbols_filtered_and_mapped_with_point_value(connected: Env) -> None:
    symbols = {s.name: s for s in connected.adapter.get_symbols()}
    # GBPUSD invisible, EURCHF trade-disabled, US500 is a non-metal CFD.
    assert sorted(symbols) == ["EURUSD", "USDJPY", "XAUUSD"]
    eur = symbols["EURUSD"]
    assert (eur.base_currency, eur.quote_currency, eur.digits) == ("EUR", "USD", 5)
    assert eur.point == Decimal("0.00001")
    assert eur.pip_size == Decimal("0.0001")
    assert eur.contract_size == Decimal(100000)
    assert (eur.volume_min, eur.volume_max, eur.volume_step) == (
        Decimal("0.01"),
        Decimal(100),
        Decimal("0.01"),
    )
    assert eur.point_value == Decimal("1.00")
    assert eur.trade_allowed is True
    assert eur.canonical_name == "EURUSD"
    assert symbols["USDJPY"].point_value == Decimal("0.6689")
    gold = symbols["XAUUSD"]
    assert gold.contract_size == Decimal(100)
    assert gold.digits == 2


def test_get_symbol_caches_and_rejects_unknown(connected: Env) -> None:
    assert connected.adapter.get_symbol("USDJPY").digits == 3
    with pytest.raises(SymbolUnavailableError):
        connected.adapter.get_symbol("GBPUSD")  # invisible in Market Watch


def test_quote_is_exact_and_utc(connected: Env) -> None:
    quote = connected.adapter.get_quote("EURUSD")
    assert quote.symbol == "EURUSD"
    assert quote.bid == Decimal("1.08500")
    assert quote.ask == Decimal("1.08512")
    assert quote.spread == Decimal("0.00012")
    # The tick lags "now" by 0.4 s and is stamped in server time (UTC+3).
    assert quote.time == datetime(2026, 10, 1, 13, 0, 4, tzinfo=UTC)
    assert quote.time.utcoffset() == timedelta(0)


def test_quote_unknown_symbol(connected: Env) -> None:
    with pytest.raises(SymbolUnavailableError):
        connected.adapter.get_quote("NOPE")


def test_candles_converted_to_utc_and_forming_bar_excluded(connected: Env) -> None:
    first = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    connected.fake.add_bars("EURUSD", H1, 3600, server_epoch(first), 6)
    candles = connected.adapter.get_candles(
        "EURUSD", Timeframe.H1, first, datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    )
    # 08..12 closed; 13:00 is still forming at 13:00:05.
    assert [c.time.hour for c in candles] == [8, 9, 10, 11, 12]
    assert all(c.time.tzinfo is not None and c.time.utcoffset() == timedelta(0) for c in candles)
    c0 = candles[0]
    assert (c0.open, c0.close) == (Decimal("1.08000"), Decimal("1.08020"))
    assert (c0.high, c0.low) == (Decimal("1.08050"), Decimal("1.07980"))
    assert c0.tick_volume == 100
    assert c0.spread_points == 9


def test_candles_window_respected(connected: Env) -> None:
    first = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    connected.fake.add_bars("EURUSD", H1, 3600, server_epoch(first), 6)
    candles = connected.adapter.get_candles(
        "EURUSD", Timeframe.H1, first + timedelta(hours=2), first + timedelta(hours=4)
    )
    assert [c.time.hour for c in candles] == [10, 11]


# ── trading state ────────────────────────────────────────────────────────────


def test_positions_mapping(connected: Env) -> None:
    opened = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    connected.fake.add_position(
        ticket=777001,
        type=1,
        volume=0.25,
        price_open=1.0861,
        sl=1.0900,
        tp=0.0,
        profit=-12.5,
        swap=-0.3,
        time=server_epoch(opened),
        comment="fxabcdef12345678 note",
    )
    [pos] = connected.adapter.get_positions()
    assert pos.position_id == "777001"
    assert pos.side is Side.SELL
    assert pos.volume == Decimal("0.25")
    assert pos.open_price == Decimal("1.08610")
    assert pos.open_time == opened
    assert pos.stop_loss == Decimal("1.09000")
    assert pos.take_profit is None  # MT5 0.0 means "no take profit"
    assert pos.unrealized_pnl == Decimal("-12.50")
    assert pos.swap == Decimal("-0.30")
    assert pos.client_order_id == "fxabcdef12345678"


def test_pending_orders_listed(connected: Env) -> None:
    req = market(
        "fxlimit00000001",
        order_type=OrderType.LIMIT,
        price=Decimal("1.08000"),
        sl="1.07500",
        tp="1.09000",
    )
    result = connected.adapter.place_order(req)
    assert result.status is OrderStatus.PENDING
    assert result.broker_position_id is None
    [order] = connected.adapter.get_orders()
    assert order.order_id == result.broker_order_id
    assert (order.side, order.order_type) == (Side.BUY, OrderType.LIMIT)
    assert order.status is OrderStatus.PENDING
    assert order.price == Decimal("1.08000")
    assert order.stop_loss == Decimal("1.07500")
    assert order.volume == Decimal("0.10")
    assert order.client_order_id == "fxlimit00000001"
    assert order.created_time == NOW.replace(microsecond=0)


def test_deals_mapping_excludes_balance_operations(connected: Env) -> None:
    connected.fake.add_deal(type=fake_mt5.DEAL_TYPE_BALANCE, profit=500.0)
    result = connected.adapter.place_order(market())
    deals = connected.adapter.get_deals(NOW - timedelta(hours=1), NOW + timedelta(minutes=1))
    [deal] = deals
    assert deal.entry is DealEntry.IN
    assert deal.side is Side.BUY
    assert deal.symbol == "EURUSD"
    assert deal.price == Decimal("1.08512")
    assert deal.volume == Decimal("0.10")
    assert deal.order_id == result.broker_order_id
    assert deal.position_id == result.broker_position_id
    assert deal.client_order_id == COID
    assert deal.reason == "EXPERT"
    assert deal.commission == Decimal("-0.35")
    assert deal.time.utcoffset() == timedelta(0)


# ── orders ───────────────────────────────────────────────────────────────────


def test_place_market_order_success(connected: Env) -> None:
    result = connected.adapter.place_order(market())
    # No slippage limit given → the field is omitted and the bridge default (20) applies.
    assert connected.fake.order_send_calls[0]["deviation"] == 20
    assert result.status is OrderStatus.FILLED
    assert result.client_order_id == COID
    assert result.fill_price == Decimal("1.08512")  # BUY fills at the ask
    assert result.filled_volume == Decimal("0.10")
    assert result.broker_order_id is not None
    assert result.broker_position_id == result.broker_order_id
    assert result.broker_code == "10009"
    [sent] = connected.fake.order_send_calls
    assert sent["comment"] == COID  # the idempotency key travels to MT5
    assert sent["sl"] == pytest.approx(1.082)
    assert sent["tp"] == pytest.approx(1.091)
    [pos] = connected.adapter.get_positions()
    assert pos.client_order_id == COID
    assert pos.position_id == result.broker_position_id


def test_explicit_slippage_limit_forwarded_as_deviation(connected: Env) -> None:
    connected.adapter.place_order(market(max_slippage_points=7))
    assert connected.fake.order_send_calls[0]["deviation"] == 7


def test_place_sell_fills_at_bid(connected: Env) -> None:
    result = connected.adapter.place_order(market(side=Side.SELL, sl="1.08800", tp="1.08000"))
    assert result.fill_price == Decimal("1.08500")


def test_place_order_is_idempotent_by_client_id(connected: Env) -> None:
    first = connected.adapter.place_order(market())
    second = connected.adapter.place_order(market())
    assert second == first
    assert len(connected.fake.order_send_calls) == 1
    assert len(connected.adapter.get_positions()) == 1


def test_partial_fill_mapped(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(fill_ratio=0.5))
    result = connected.adapter.place_order(market(volume="0.20"))
    assert result.status is OrderStatus.PARTIALLY_FILLED
    assert result.filled_volume == Decimal("0.10")


def test_market_closed_maps_to_market_closed_error(connected: Env) -> None:
    connected.fake.market_closed = True
    with pytest.raises(MarketClosedError) as info:
        connected.adapter.place_order(market())
    assert info.value.broker_code == "10018"
    assert connected.fake.positions == {}


def test_no_money_maps_to_insufficient_margin(connected: Env) -> None:
    with pytest.raises(InsufficientMarginError) as info:
        connected.adapter.place_order(market(volume="50"))
    assert info.value.broker_code == "10019"
    assert connected.fake.positions == {}


def test_invalid_stops_is_plain_rejection(connected: Env) -> None:
    with pytest.raises(OrderRejectedError) as info:
        connected.adapter.place_order(market(sl="1.09000"))
    assert type(info.value) is OrderRejectedError
    assert info.value.broker_code == "10016"


def test_generic_retcode_rejection(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(retcode=10006))
    with pytest.raises(OrderRejectedError) as info:
        connected.adapter.place_order(market())
    assert type(info.value) is OrderRejectedError
    assert info.value.broker_code == "10006"


def test_rejected_order_lookup_returns_rejected_result(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(retcode=10006))
    with pytest.raises(OrderRejectedError):
        connected.adapter.place_order(market())
    found = connected.adapter.find_order_by_client_id(COID)
    assert found is not None
    assert found.status is OrderStatus.REJECTED
    assert found.broker_code == "10006"
    # Retrying with the same id never sends again; the stored rejection is replayed.
    with pytest.raises(OrderRejectedError):
        connected.adapter.place_order(market())
    assert len(connected.fake.order_send_calls) == 1


def test_bridge_invalid_request_is_rejection(connected: Env) -> None:
    # Client order ids must be 8-24 lowercase alphanumerics.
    with pytest.raises(OrderRejectedError, match="Bridge rejected request"):
        connected.adapter.place_order(market("BAD-ID"))
    assert connected.fake.order_send_calls == []


def test_trade_server_timeout_retcode_is_outcome_unknown(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(retcode=10012))
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.place_order(market())
    assert info.value.client_order_id == COID


def test_lost_result_but_executed_reconciles_to_filled(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(return_none=True, execute=True))
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.place_order(market())
    assert info.value.client_order_id == COID
    found = connected.adapter.find_order_by_client_id(COID)
    assert found is not None
    assert found.status is OrderStatus.FILLED
    assert found.filled_volume == Decimal("0.10")
    assert found.fill_price == Decimal("1.08512")
    assert found.broker_position_id is not None
    # A retry with the same id returns the recovered result without resending.
    again = connected.adapter.place_order(market())
    assert again.status is OrderStatus.FILLED
    assert len(connected.fake.order_send_calls) == 1
    assert len(connected.fake.positions) == 1


def test_lost_result_not_executed_stays_unknown_and_is_never_resent(connected: Env) -> None:
    connected.fake.send_behaviours.append(fake_mt5.SendBehaviour(return_none=True, execute=False))
    with pytest.raises(OrderOutcomeUnknownError):
        connected.adapter.place_order(market())
    with pytest.raises(OrderOutcomeUnknownError):
        connected.adapter.find_order_by_client_id(COID)
    with pytest.raises(OrderOutcomeUnknownError):
        connected.adapter.place_order(market())
    assert len(connected.fake.order_send_calls) == 1
    assert connected.fake.positions == {}


def test_find_unknown_client_id_returns_none(connected: Env) -> None:
    assert connected.adapter.find_order_by_client_id("fxneverseen000001") is None


def test_close_position_full_and_partial(connected: Env) -> None:
    opened = connected.adapter.place_order(market(volume="0.30"))
    pid = opened.broker_position_id
    assert pid is not None
    partial = connected.adapter.close_position(pid, "fxclose000000001", Decimal("0.10"))
    assert partial.status is OrderStatus.FILLED
    assert partial.filled_volume == Decimal("0.10")
    assert partial.fill_price == Decimal("1.08500")  # a long closes at the bid
    assert partial.broker_position_id == pid
    [pos] = connected.adapter.get_positions()
    assert pos.volume == Decimal("0.20")
    final = connected.adapter.close_position(pid, "fxclose000000002")
    assert final.filled_volume == Decimal("0.20")
    assert connected.adapter.get_positions() == []
    # Idempotent close: same client id → same result, no new order_send.
    sends = len(connected.fake.order_send_calls)
    assert connected.adapter.close_position(pid, "fxclose000000002") == final
    assert len(connected.fake.order_send_calls) == sends


def test_close_unknown_position_not_found(connected: Env) -> None:
    with pytest.raises(NotFoundError):
        connected.adapter.close_position("999999", "fxclose000000009")


def test_modify_position_sets_and_removes_stops(connected: Env) -> None:
    opened = connected.adapter.place_order(market())
    pid = opened.broker_position_id
    assert pid is not None
    result = connected.adapter.modify_position(pid, Decimal("1.08300"), None)
    assert result.status is OrderStatus.FILLED
    assert result.client_order_id == COID
    [pos] = connected.adapter.get_positions()
    assert pos.stop_loss == Decimal("1.08300")
    assert pos.take_profit is None


def test_modify_and_cancel_pending_order(connected: Env) -> None:
    placed = connected.adapter.place_order(
        market(
            "fxlimit00000002",
            order_type=OrderType.LIMIT,
            price=Decimal("1.08000"),
            sl="1.07500",
            tp="1.09000",
        )
    )
    oid = placed.broker_order_id
    assert oid is not None
    modified = connected.adapter.modify_order(
        oid,
        OrderModification(price=Decimal("1.07900"), stop_loss=Decimal("1.07400"), take_profit=None),
    )
    assert modified.status is OrderStatus.PENDING
    [order] = connected.adapter.get_orders()
    assert order.price == Decimal("1.07900")
    assert order.stop_loss == Decimal("1.07400")
    assert order.take_profit is None
    cancelled = connected.adapter.cancel_order(oid)
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.client_order_id == "fxlimit00000002"
    assert connected.adapter.get_orders() == []


def test_cancel_unknown_order_not_found(connected: Env) -> None:
    with pytest.raises(NotFoundError):
        connected.adapter.cancel_order("123")


# ── authentication & response integrity ──────────────────────────────────────


def test_wrong_secret_is_auth_error(env: Env) -> None:
    adapter = env.make_adapter(secret=WRONG_SECRET)
    with pytest.raises(BrokerAuthError, match="BRIDGE_SECRET"):
        adapter.connect()
    assert not adapter.is_connected
    assert env.fake.login_calls == []  # the bridge refused before touching MT5


def test_wrong_secret_trade_is_outcome_unknown_and_nothing_executes(connected: Env) -> None:
    adapter = connected.make_adapter(secret=WRONG_SECRET)
    with pytest.raises(OrderOutcomeUnknownError):
        adapter.place_order(market())
    assert connected.fake.order_send_calls == []


def test_clock_skew_is_auth_error(connected: Env) -> None:
    skewed = connected.make_adapter(clock=lambda: connected.clock() + 120)
    with pytest.raises(BrokerAuthError, match="BRIDGE_SECRET and clocks"):
        skewed.get_account()


def _tamper_signature(request: httpx.Request, response: httpx.Response) -> httpx.Response:
    headers = dict(response.headers)
    headers["x-fx-signature"] = "0" * 64
    headers.pop("content-length", None)
    return httpx.Response(response.status_code, headers=headers, content=response.content)


def test_tampered_signature_on_read_is_invalid_response(connected: Env) -> None:
    connected.transport.rewrite = _tamper_signature
    with pytest.raises(InvalidBrokerResponseError):
        connected.adapter.get_account()


def test_tampered_body_on_read_is_invalid_response(connected: Env) -> None:
    def rewrite(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        body = response.content.replace(b"10000.00", b"99999.00")
        headers = {k: v for k, v in response.headers.items() if k != "content-length"}
        return httpx.Response(response.status_code, headers=headers, content=body)

    connected.transport.rewrite = rewrite
    with pytest.raises(InvalidBrokerResponseError):
        connected.adapter.get_account()


def test_tampered_signature_on_trade_is_outcome_unknown_then_reconciles(connected: Env) -> None:
    connected.transport.rewrite = _tamper_signature
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.place_order(market())
    assert info.value.client_order_id == COID
    # The bridge DID execute it — reconciliation over a clean link finds it.
    connected.transport.rewrite = None
    found = connected.adapter.find_order_by_client_id(COID)
    assert found is not None
    assert found.status is OrderStatus.FILLED
    assert len(connected.fake.order_send_calls) == 1


def test_tampered_signature_on_close_is_outcome_unknown(connected: Env) -> None:
    pid = connected.adapter.place_order(market()).broker_position_id
    assert pid is not None
    connected.transport.rewrite = _tamper_signature
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.close_position(pid, "fxclose000000003")
    assert info.value.client_order_id == "fxclose000000003"


def _malformed(request: httpx.Request, response: httpx.Response) -> httpx.Response:
    return resign(request, 200, b"{not json", response.headers)


def test_malformed_json_on_read_is_invalid_response(connected: Env) -> None:
    connected.transport.rewrite = _malformed
    with pytest.raises(InvalidBrokerResponseError, match="malformed JSON"):
        connected.adapter.get_positions()


def test_malformed_json_on_trade_is_outcome_unknown(connected: Env) -> None:
    connected.transport.rewrite = _malformed
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.place_order(market())
    assert info.value.client_order_id == COID


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"account_id": "1"},  # required fields missing
        {"account_id": "1", "currency": "USD", "balance": "NaN", "equity": "1"},
        {"account_id": "1", "currency": "USD", "balance": "abc", "equity": "1"},
    ],
)
def test_wrong_shape_account_is_invalid_response(connected: Env, payload: Any) -> None:
    def rewrite(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        return resign(request, 200, json.dumps(payload).encode(), response.headers)

    connected.transport.rewrite = rewrite
    with pytest.raises(InvalidBrokerResponseError):
        connected.adapter.get_account()


def test_naive_timestamp_is_invalid_response(connected: Env) -> None:
    def rewrite(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        payload = response.json()
        payload["time"] = "2026-10-01T13:00:04"
        return resign(request, 200, json.dumps(payload).encode(), response.headers)

    connected.transport.rewrite = rewrite
    with pytest.raises(InvalidBrokerResponseError, match="timezone"):
        connected.adapter.get_quote("EURUSD")


def test_unparseable_trade_result_is_outcome_unknown(connected: Env) -> None:
    def rewrite(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        payload = response.json()
        payload["status"] = "DONE-ISH"
        return resign(request, 200, json.dumps(payload).encode(), response.headers)

    connected.transport.rewrite = rewrite
    with pytest.raises(OrderOutcomeUnknownError, match="Unparseable"):
        connected.adapter.place_order(market())


def test_link_failure_read_is_connection_error(connected: Env) -> None:
    connected.transport.fail_with = httpx.ConnectError("refused")
    with pytest.raises(BrokerConnectionError):
        connected.adapter.get_account()
    assert not connected.adapter.is_connected


def test_link_failure_trade_is_outcome_unknown(connected: Env) -> None:
    connected.transport.fail_with = httpx.ReadError("reset")
    with pytest.raises(OrderOutcomeUnknownError) as info:
        connected.adapter.place_order(market())
    assert info.value.client_order_id == COID


def test_read_timeout_is_retryable_timeout_error(connected: Env) -> None:
    from fxrobot.broker_engine.errors import BrokerTimeoutError

    connected.transport.fail_with = httpx.ReadTimeout("slow")
    with pytest.raises(BrokerTimeoutError):
        connected.adapter.get_positions()
