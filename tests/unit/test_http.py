from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from power_market.http import ExtractError, HttpClient, NotFoundError, RateLimiter
from tests.conftest import SleepRecorder

MakeHttp = Callable[[Callable[[httpx.Request], httpx.Response]], HttpClient]
URL = "https://example.test/data.json"


def sequence(*responses: httpx.Response | Exception) -> Callable[[httpx.Request], httpx.Response]:
    """Handler that returns (or raises) the given items in order."""
    items = list(responses)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        item = items[min(calls["n"], len(items) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


def test_returns_successful_response(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    with make_http(sequence(httpx.Response(200, json={"ok": True}))) as http:
        assert http.get(URL).json() == {"ok": True}
    assert sleeps.calls == []


def test_retries_server_errors_then_succeeds(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    handler = sequence(httpx.Response(503), httpx.Response(502), httpx.Response(200, text="ok"))
    assert make_http(handler).get(URL).text == "ok"
    assert handler.calls["n"] == 3  # type: ignore[attr-defined]
    assert len(sleeps.calls) == 2


def test_retries_timeouts_and_gives_up(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    handler = sequence(httpx.ReadTimeout("slow"))
    with pytest.raises(ExtractError, match="after 4 attempts: ReadTimeout"):
        make_http(handler).get(URL)
    assert handler.calls["n"] == 4  # type: ignore[attr-defined]
    assert len(sleeps.calls) == 3  # no sleep after the final attempt


def test_backoff_grows_exponentially(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    with pytest.raises(ExtractError):
        make_http(sequence(httpx.ConnectError("down"))).get(URL)
    # full jitter within [ceiling/2, ceiling] with ceilings 1, 2, 4
    for delay, ceiling in zip(sleeps.calls, [1, 2, 4], strict=True):
        assert ceiling / 2 <= delay <= ceiling


def test_backoff_is_capped() -> None:
    http = HttpClient(backoff_base_seconds=10)
    assert http.backoff_delay(attempt=10) <= 60


def test_honours_retry_after(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    handler = sequence(httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200))
    make_http(handler).get(URL)
    assert sleeps.calls == [7.0]


def test_404_is_not_retried(make_http: MakeHttp, sleeps: SleepRecorder) -> None:
    handler = sequence(httpx.Response(404))
    with pytest.raises(NotFoundError):
        make_http(handler).get(URL)
    assert handler.calls["n"] == 1  # type: ignore[attr-defined]
    assert sleeps.calls == []


def test_client_errors_fail_fast_with_body(make_http: MakeHttp) -> None:
    handler = sequence(httpx.Response(400, json={"error": True, "reason": "end_date out of range"}))
    with pytest.raises(ExtractError, match=r"HTTP 400.*end_date out of range"):
        make_http(handler).get(URL)
    assert handler.calls["n"] == 1  # type: ignore[attr-defined]


def test_passes_query_params(make_http: MakeHttp) -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200)

    make_http(handler).get(URL, params={"a": 1, "b": "x"})
    assert seen[0].params == httpx.QueryParams({"a": "1", "b": "x"})
    assert seen[0].host == "example.test"


def test_rate_limiter_spaces_calls() -> None:
    now = {"t": 100.0}
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["t"] += seconds

    limiter = RateLimiter(rate_per_second=2, clock=lambda: now["t"], sleep=sleep)
    for _ in range(3):
        limiter.acquire()
    assert slept == [0.5, 0.5]


def test_rate_limiter_does_not_wait_after_idle_time() -> None:
    now = {"t": 0.0}
    slept: list[float] = []
    limiter = RateLimiter(rate_per_second=1, clock=lambda: now["t"], sleep=slept.append)
    limiter.acquire()
    now["t"] = 5.0
    limiter.acquire()
    assert slept == []
