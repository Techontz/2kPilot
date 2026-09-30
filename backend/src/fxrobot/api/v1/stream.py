"""Server-Sent Events stream for real-time dashboard updates.

One authenticated, read-only channel; the browser refreshes the affected
views when events arrive instead of polling every endpoint.
"""

from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from fxrobot.api.deps import CurrentUserDep
from fxrobot.core.events import Event, bus

router = APIRouter(tags=["stream"])

KEEPALIVE_SECONDS = 15.0


def _format(event: Event) -> str:
    payload = json.dumps(
        {"topic": event.topic, "at": event.at.isoformat(), "data": event.data}, default=str
    )
    return f"event: {event.topic}\ndata: {payload}\n\n"


@router.get("/stream")
async def stream(request: Request, _: CurrentUserDep) -> StreamingResponse:
    q = bus.subscribe()

    async def generator() -> AsyncIterator[str]:
        try:
            yield "retry: 5000\n\n"
            idle = 0.0
            while not await request.is_disconnected():
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.25)
                    idle += 0.25
                    if idle >= KEEPALIVE_SECONDS:
                        idle = 0.0
                        yield ": keepalive\n\n"
                    continue
                idle = 0.0
                yield _format(event)
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
