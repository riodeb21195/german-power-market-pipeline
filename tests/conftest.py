from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from power_market.http import HttpClient, RateLimiter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes() -> Callable[[str], bytes]:
    """Load a recorded API response, e.g. `fixture_bytes("smard/index_4169_DE-LU_hour.json")`."""

    def load(relative: str) -> bytes:
        return (FIXTURES / relative).read_bytes()

    return load


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeps() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def make_http(
    sleeps: SleepRecorder,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], HttpClient]:
    """Build an HttpClient backed by a handler function instead of the network."""

    def build(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
        return HttpClient(
            max_retries=3,
            backoff_base_seconds=1.0,
            transport=httpx.MockTransport(handler),
            sleep=sleeps,
            # keep rate-limit waits out of the recorded backoff sleeps
            rate_limiter=RateLimiter(1000.0, sleep=lambda _: None),
        )

    return build
