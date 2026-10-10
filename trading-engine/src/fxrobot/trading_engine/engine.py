"""Engine supervisor: leadership lease, heartbeat, per-account worker threads.

One account is never ticked twice at the same time. A tick that outlives
ACCOUNT_TICK_TIMEOUT cannot be cancelled (it may be inside a broker call), so
the account stays "in flight" and later cycles skip it until that tick ends.

Across processes: the leadership LEASE outlives a whole cycle and is renewed
while ticks run, and every tick additionally holds a per-account database lock
(MySQL `GET_LOCK('tp:acct:<id>', 0)` on a connection of its own, released when
the tick ends or the process dies), so even if a lease is lost mid-cycle a
second engine process can never tick the same account concurrently.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from datetime import timedelta

from sqlalchemy import Engine, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.db.types import utcnow
from fxrobot.models import BrokerConnection, SystemState, TradingAccount
from fxrobot.notifications.service import notify
from fxrobot.trading_engine.runner import AccountRunner, TickResult

logger = logging.getLogger(__name__)

ACCOUNT_LOCKED = "account is being ticked by another engine process"

ACCOUNT_TICK_TIMEOUT = 45.0
LEASE = timedelta(seconds=90)  # > ACCOUNT_TICK_TIMEOUT: a cycle never outlives its lease
LEASE_RENEW_EVERY = 10.0  # seconds, while a cycle waits for its ticks


class TradingEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        manager: BrokerManager,
        *,
        live_locked: bool,
        tick_seconds: float = 2.0,
    ) -> None:
        self._sf = session_factory
        self.manager = manager
        self.runner = AccountRunner(manager, live_locked=live_locked)
        self.tick_seconds = tick_seconds
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fx-account")
        self.is_leader = False
        self._db_down_notified = False
        self._in_flight: set[uuid.UUID] = set()  # accounts with a tick still running
        self._in_flight_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fx-engine", daemon=True)
        self._thread.start()
        logger.info("trading engine started (%s)", self.owner)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.manager.flush_all()
        self._release_lease()
        logger.info("trading engine stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
                self._db_down_notified = False
            except SQLAlchemyError:
                # Database unavailable: do nothing (no DB = no safe decisions), retry.
                if not self._db_down_notified:
                    logger.exception("database unavailable — engine paused until it returns")
                    self._db_down_notified = True
            except Exception:
                logger.exception("engine cycle failed")
                self._notify_error("Trading engine cycle failed; see server logs.")
            self._stop.wait(self.tick_seconds)

    # ── leadership ───────────────────────────────────────────────────────
    def _acquire_lease(self, db: Session) -> bool:
        now = utcnow()
        result = db.execute(
            update(SystemState)
            .where(SystemState.id == 1)
            .where(
                or_(
                    SystemState.engine_owner.is_(None),
                    SystemState.engine_owner == self.owner,
                    SystemState.engine_lease_until < now,
                )
            )
            .values(engine_owner=self.owner, engine_lease_until=now + LEASE)
        )
        db.commit()
        leader = bool(result.rowcount)  # type: ignore[attr-defined]
        if leader and not self.is_leader:
            logger.info("engine leadership acquired")
        self.is_leader = leader
        return leader

    def _renew_lease(self) -> None:
        """Keep leadership while ticks are still running (best effort: the
        per-account locks protect the accounts even if it is lost)."""
        try:
            with self._sf() as db:
                if not self._acquire_lease(db):
                    logger.warning("engine leadership lost during a cycle")
        except SQLAlchemyError:
            logger.warning("could not renew the engine lease")

    def _release_lease(self) -> None:
        try:
            with self._sf() as db:
                db.execute(
                    update(SystemState)
                    .where(SystemState.engine_owner == self.owner)
                    .values(engine_owner=None, engine_lease_until=None)
                )
                db.commit()
        except SQLAlchemyError:
            pass

    # ── cycle ────────────────────────────────────────────────────────────
    def run_cycle(self) -> list[TickResult]:
        with self._sf() as db:
            if not self._acquire_lease(db):
                return []
            account_ids = list(
                db.scalars(
                    select(TradingAccount.id)
                    .join(BrokerConnection)
                    .where(BrokerConnection.is_enabled.is_(True))
                )
            )
        results: list[TickResult] = []
        futures = {}
        for aid in account_ids:
            if not self._claim(aid):
                logger.warning("account %s: previous tick still running — skipped", aid)
                results.append(TickResult(aid, False, "previous tick still running"))
                continue
            futures[self._pool.submit(self._tick_account, aid)] = aid
        deadline = time.monotonic() + ACCOUNT_TICK_TIMEOUT
        pending = set(futures)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _, pending = wait(pending, timeout=min(remaining, LEASE_RENEW_EVERY))
            if pending:
                self._renew_lease()
        done = set(futures) - pending
        for future in done:
            try:
                results.append(future.result())
            except Exception as exc:
                logger.exception("account tick crashed")
                results.append(TickResult(futures[future], False, f"internal error: {exc}"))
        for future in pending:
            results.append(TickResult(futures[future], False, "tick timed out"))
        self._heartbeat(results)
        return results

    def _claim(self, account_id: uuid.UUID) -> bool:
        with self._in_flight_lock:
            if account_id in self._in_flight:
                return False
            self._in_flight.add(account_id)
            return True

    def _tick_account(self, account_id: uuid.UUID) -> TickResult:
        try:
            with self._account_lock(account_id) as locked:
                if not locked:
                    logger.warning(
                        "account %s: ticked by another engine process — skipped", account_id
                    )
                    return TickResult(account_id, False, ACCOUNT_LOCKED)
                with self._sf() as db:
                    return self.runner.tick(db, account_id)
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(account_id)

    @contextlib.contextmanager
    def _account_lock(self, account_id: uuid.UUID) -> Iterator[bool]:
        """Hold the account's database lock for the whole tick (yields False if
        another process holds it). The lock lives on its own connection, so the
        tick's commits cannot hand it to the pool."""
        bind = self._sf.kw.get("bind")
        if not isinstance(bind, Engine) or bind.dialect.name != "mysql":
            yield True  # no named locks (tests on other databases): in-process guard only
            return
        name = f"tp:acct:{account_id}"
        with bind.connect() as conn:
            got = conn.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": name}).scalar()
            conn.rollback()  # named locks are not transactional: keep no transaction open
            if got != 1:
                yield False
                return
            try:
                yield True
            finally:
                try:
                    conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
                    conn.rollback()
                except SQLAlchemyError:
                    conn.invalidate()  # closing the connection frees the lock

    def _heartbeat(self, results: list[TickResult]) -> None:
        failing = [r for r in results if not r.ok]
        detail = (
            f"{len(results)} account(s); "
            + (
                "all healthy"
                if not failing
                else f"{len(failing)} with problems: {failing[0].detail}"
            )
        )[:500]
        with self._sf() as db:
            db.execute(
                update(SystemState)
                .where(SystemState.id == 1)
                .values(
                    engine_heartbeat_at=utcnow(),
                    engine_detail=detail,
                    engine_degraded=bool(failing),
                )
            )
            db.commit()

    def _notify_error(self, message: str) -> None:
        try:
            with self._sf() as db:
                notify(db, "system.error", message)
        except Exception:
            logger.exception("could not record system error notification")

    def tick_once(self) -> list[TickResult]:
        """Run one synchronous cycle (tests and CLI)."""
        return self.run_cycle()

    def wait(self, timeout: float) -> None:
        with contextlib.suppress(TimeoutError):
            self._stop.wait(timeout)
