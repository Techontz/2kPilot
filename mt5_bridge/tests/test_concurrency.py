from __future__ import annotations

import asyncio
import json
import threading

import httpx
from fastapi import FastAPI

from .conftest import FakeClock, order_body, signed_headers
from .fake_mt5 import FakeMT5, SendBehaviour


async def _call(
    ac: httpx.AsyncClient, clock: FakeClock, method: str, path: str, body: object = None
) -> httpx.Response:
    data = b"" if body is None else json.dumps(body).encode()
    return await ac.request(
        method, path, content=data, headers=signed_headers(method, path, data, clock())
    )


def test_all_terminal_calls_on_one_thread(app: FastAPI, fake: FakeMT5, clock: FakeClock) -> None:
    fake.call_delay = 0.005

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as ac:
            paths = [
                "/v1/positions",
                "/v1/orders",
                "/v1/account",
                "/v1/symbols",
                "/v1/quotes/EURUSD",
                "/v1/health",
            ] * 4
            return await asyncio.gather(*(_call(ac, clock, "GET", p) for p in paths))

    responses = asyncio.run(run())
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert fake.max_concurrency == 1
    assert len(fake.thread_ids) == 1
    assert threading.get_ident() not in fake.thread_ids


def test_concurrent_duplicate_submissions_send_once(
    app: FastAPI, fake: FakeMT5, clock: FakeClock
) -> None:
    fake.send_behaviours.append(SendBehaviour(delay=0.2))

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as ac:
            return await asyncio.gather(
                *(_call(ac, clock, "POST", "/v1/orders", order_body()) for _ in range(5))
            )

    responses = asyncio.run(run())
    assert [r.status_code for r in responses] == [200] * 5
    assert len({r.text for r in responses}) == 1
    assert len(fake.order_send_calls) == 1
    assert fake.max_concurrency == 1
