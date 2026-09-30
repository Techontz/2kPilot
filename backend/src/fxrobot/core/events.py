"""In-process publish/subscribe used for real-time dashboard updates (SSE).

Thread-safe: the trading engine publishes from worker threads; the SSE
endpoint consumes from the event loop. Slow subscribers drop old events
rather than blocking publishers.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_QUEUE = 500


@dataclass(frozen=True)
class Event:
    topic: str  # e.g. "status", "notification", "position", "order", "signal", "quote"
    data: dict[str, Any]
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[Event]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue(maxsize=MAX_QUEUE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, topic: str, data: dict[str, Any]) -> None:
        event = Event(topic, data)
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()  # drop the oldest
                    q.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


bus = EventBus()
