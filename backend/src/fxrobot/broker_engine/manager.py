"""Process-wide registry of live broker adapters.

Responsibilities:
* one adapter instance per connection (paper simulators hold state!);
* connect lazily, reconnect with exponential backoff, never hammer a broker;
* persist status transitions (CONNECTED / DISCONNECTED / RECONNECTING / ERROR)
  and raise notifications for them;
* persist PAPER simulator state so it survives restarts.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from fxrobot.broker_engine.adapters.paper import FaultInjector
from fxrobot.broker_engine.errors import BrokerAuthError, BrokerConnectionError, BrokerError
from fxrobot.broker_engine.factory import ConfigurationError, build_adapter
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.core.crypto import SecretBox
from fxrobot.core.events import bus
from fxrobot.db.types import utcnow
from fxrobot.domain.trading import ConnectionStatus
from fxrobot.models import BrokerConnection, PaperState, TradingAccount
from fxrobot.notifications.service import notify

logger = logging.getLogger(__name__)

MAX_BACKOFF = 60.0
HEALTH_INTERVAL = 10.0
PAPER_SAVE_INTERVAL = 2.0


@dataclass
class _Entry:
    adapter: BrokerAdapter
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    failures: int = 0
    next_attempt: float = 0.0
    last_health: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_paper_save: float = 0.0
    pending_paper_state: dict[str, Any] | None = None


class BrokerManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        secret_box: SecretBox | None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sf = session_factory
        self._box = secret_box
        self._mono = monotonic
        self._entries: dict[uuid.UUID, _Entry] = {}
        self._lock = threading.Lock()
        self.faults: dict[uuid.UUID, FaultInjector] = {}  # test/chaos hooks for paper brokers

    # ── lifecycle ────────────────────────────────────────────────────────
    def _entry(self, connection_id: uuid.UUID) -> _Entry:
        with self._lock:
            entry = self._entries.get(connection_id)
            if entry is not None:
                return entry
        with self._sf() as db:
            connection = db.get(BrokerConnection, connection_id)
            if connection is None:
                raise BrokerConnectionError("Connection not found")
            if not connection.is_enabled:
                raise BrokerConnectionError("Connection is disabled")

            def on_paper_change(state: dict[str, Any], important: bool) -> None:
                self._paper_changed(connection_id, state, important)

            try:
                adapter = build_adapter(
                    db,
                    connection,
                    self._box,
                    on_paper_change=on_paper_change,
                    faults=self.faults.setdefault(connection_id, FaultInjector()),
                )
            except ConfigurationError as exc:
                self._set_status(connection_id, ConnectionStatus.ERROR, str(exc))
                raise BrokerConnectionError(str(exc)) from exc
        with self._lock:
            return self._entries.setdefault(connection_id, _Entry(adapter))

    def evict(self, connection_id: uuid.UUID) -> None:
        with self._lock:
            entry = self._entries.pop(connection_id, None)
        if entry is not None:
            self._flush_paper(connection_id, entry, force=True)
            with contextlib.suppress(BrokerError):
                entry.adapter.disconnect()

    def shutdown(self) -> None:
        for connection_id in list(self._entries):
            self.evict(connection_id)

    # ── access ───────────────────────────────────────────────────────────
    def get(self, connection_id: uuid.UUID) -> BrokerAdapter:
        """A connected adapter, reconnecting if allowed by the backoff schedule."""
        entry = self._entry(connection_id)
        with entry.lock:
            if entry.adapter.is_connected:
                if entry.status is not ConnectionStatus.CONNECTED:
                    # The link recovered by itself (e.g. a transient outage ended).
                    entry.failures, entry.next_attempt = 0, 0.0
                    self._transition(connection_id, entry, ConnectionStatus.CONNECTED, "Connected")
                return entry.adapter
            now = self._mono()
            if now < entry.next_attempt:
                wait = int(entry.next_attempt - now) + 1
                raise BrokerConnectionError(
                    f"Broker disconnected — next reconnect attempt in {wait}s"
                )
            previous = entry.status
            try:
                entry.adapter.connect()
            except BrokerAuthError as exc:
                entry.failures += 1
                entry.next_attempt = now + MAX_BACKOFF  # don't spam bad credentials
                self._transition(connection_id, entry, ConnectionStatus.ERROR, str(exc))
                raise
            except BrokerError as exc:
                entry.failures += 1
                entry.next_attempt = now + min(MAX_BACKOFF, 2.0 ** min(entry.failures, 6))
                status = (
                    ConnectionStatus.RECONNECTING
                    if previous in (ConnectionStatus.CONNECTED, ConnectionStatus.RECONNECTING)
                    else ConnectionStatus.ERROR
                )
                self._transition(connection_id, entry, status, str(exc))
                raise BrokerConnectionError(str(exc)) from exc
            entry.failures = 0
            entry.next_attempt = 0.0
            entry.last_health = now
            self._transition(connection_id, entry, ConnectionStatus.CONNECTED, "Connected")
            return entry.adapter

    def peek(self, connection_id: uuid.UUID) -> BrokerAdapter | None:
        """The adapter if one exists, without connecting."""
        entry = self._entries.get(connection_id)
        return entry.adapter if entry else None

    def status(self, connection_id: uuid.UUID) -> ConnectionStatus:
        entry = self._entries.get(connection_id)
        return entry.status if entry else ConnectionStatus.DISCONNECTED

    def check_health(self, connection_id: uuid.UUID, *, force: bool = False) -> bool:
        """Probe the connection (throttled). Marks it disconnected on failure."""
        entry = self._entry(connection_id)
        now = self._mono()
        if not force and now - entry.last_health < HEALTH_INTERVAL:
            return entry.adapter.is_connected
        entry.last_health = now
        with entry.lock:
            health = entry.adapter.health()
            if health.connected:
                if entry.status is not ConnectionStatus.CONNECTED:
                    self._transition(
                        connection_id, entry, ConnectionStatus.CONNECTED, health.detail
                    )
                return True
            if entry.status is ConnectionStatus.CONNECTED:
                entry.next_attempt = now + 2.0
                self._transition(connection_id, entry, ConnectionStatus.RECONNECTING, health.detail)
            return False

    def mark_failure(self, connection_id: uuid.UUID, detail: str) -> None:
        """Called by callers that saw a connection error mid-operation."""
        entry = self._entries.get(connection_id)
        if entry is None:
            return
        with entry.lock:
            with contextlib.suppress(BrokerError):
                entry.adapter.disconnect()
            entry.next_attempt = self._mono() + 2.0
            self._transition(connection_id, entry, ConnectionStatus.RECONNECTING, detail)

    # ── status & notifications ───────────────────────────────────────────
    def _transition(
        self, connection_id: uuid.UUID, entry: _Entry, status: ConnectionStatus, detail: str
    ) -> None:
        previous = entry.status
        entry.status = status
        if previous is status:
            return
        self._set_status(connection_id, status, detail)
        with self._sf() as db:
            account = db.query(TradingAccount).filter_by(connection_id=connection_id).first()
            account_id = account.id if account else None
            label = db.get(BrokerConnection, connection_id)
            name = label.label if label else "Broker"
            if status is ConnectionStatus.CONNECTED:
                kind = (
                    "broker.reconnected"
                    if previous is ConnectionStatus.RECONNECTING
                    else "broker.connected"
                )
                notify(db, kind, f"{name}: {detail}", account_id=account_id)
            elif status is ConnectionStatus.RECONNECTING:
                notify(
                    db,
                    "broker.disconnected",
                    f"{name}: {detail}. Reconnecting…",
                    account_id=account_id,
                )
            elif status is ConnectionStatus.ERROR:
                notify(db, "broker.error", f"{name}: {detail}", account_id=account_id)
        logger.info("broker %s %s -> %s: %s", connection_id, previous, status, detail)

    def _set_status(self, connection_id: uuid.UUID, status: ConnectionStatus, detail: str) -> None:
        with self._sf() as db:
            connection = db.get(BrokerConnection, connection_id)
            if connection is None:
                return
            connection.status = status
            connection.status_detail = detail[:500]
            if status is ConnectionStatus.CONNECTED:
                connection.last_connected_at = utcnow()
            elif status is ConnectionStatus.ERROR:
                connection.last_error_at = utcnow()
            db.commit()
        bus.publish(
            "broker",
            {"connection_id": str(connection_id), "status": status.value, "detail": detail},
        )

    # ── paper persistence ────────────────────────────────────────────────
    def _paper_changed(
        self, connection_id: uuid.UUID, state: dict[str, Any], important: bool
    ) -> None:
        entry = self._entries.get(connection_id)
        if entry is None:
            self._write_paper_state(connection_id, state)
            return
        entry.pending_paper_state = state
        self._flush_paper(connection_id, entry, force=important)

    def _flush_paper(self, connection_id: uuid.UUID, entry: _Entry, *, force: bool = False) -> None:
        if entry.pending_paper_state is None:
            return
        now = self._mono()
        if not force and now - entry.last_paper_save < PAPER_SAVE_INTERVAL:
            return
        state, entry.pending_paper_state = entry.pending_paper_state, None
        entry.last_paper_save = now
        self._write_paper_state(connection_id, state)

    def flush_all(self) -> None:
        for connection_id, entry in list(self._entries.items()):
            self._flush_paper(connection_id, entry, force=True)

    def _write_paper_state(self, connection_id: uuid.UUID, state: dict[str, Any]) -> None:
        try:
            with self._sf() as db:
                row = db.get(PaperState, connection_id)
                if row is None:
                    db.add(PaperState(connection_id=connection_id, state=state))
                else:
                    row.state = state
                db.commit()
        except Exception:
            logger.exception("failed to persist paper state for %s", connection_id)
