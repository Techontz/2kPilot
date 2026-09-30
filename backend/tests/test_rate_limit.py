from fxrobot.core.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_sliding_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(2, 60, clock=clock)
    assert limiter.retry_after("k") == 0
    limiter.hit("k")
    limiter.hit("k")
    assert limiter.retry_after("k") == 60
    clock.now += 30
    assert limiter.retry_after("k") == 30
    clock.now += 30
    assert limiter.retry_after("k") == 0


def test_keys_are_independent_and_resettable() -> None:
    limiter = SlidingWindowRateLimiter(1, 60, clock=FakeClock())
    limiter.hit("a")
    assert limiter.retry_after("a") > 0
    assert limiter.retry_after("b") == 0
    limiter.reset("a")
    assert limiter.retry_after("a") == 0
