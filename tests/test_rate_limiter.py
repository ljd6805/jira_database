from __future__ import annotations

from jira_collector.rate_limiter import IntervalRateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_twenty_per_minute_means_three_second_interval() -> None:
    fake = FakeTime()
    limiter = IntervalRateLimiter(20, clock=fake.clock, sleeper=fake.sleep)

    limiter.wait()
    limiter.wait()
    fake.now += 1.0
    limiter.wait()

    assert limiter.interval_seconds == 3.0
    assert fake.sleeps == [3.0, 2.0]
