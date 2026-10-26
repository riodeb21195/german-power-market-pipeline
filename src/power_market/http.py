"""HTTP client with timeouts, rate limiting and retry with exponential backoff."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from power_market import __version__

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 60.0


class ExtractError(Exception):
    """Raised when a source cannot be read (after retries)."""


class NotFoundError(ExtractError):
    """The requested resource does not exist (HTTP 404). Not retried."""


class RateLimiter:
    """Allow at most `rate_per_second` calls by spacing them evenly (thread-safe)."""

    def __init__(
        self,
        rate_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = 1.0 / rate_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._next_allowed = now + self._interval


class HttpClient:
    """Thin wrapper around `httpx.Client` adding the resilience the sources need."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
        backoff_base_seconds: float = 1.0,
        rate_limit_per_second: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep
        self._limiter = rate_limiter or RateLimiter(rate_limit_per_second, sleep=sleep)
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"User-Agent": f"power-market-pipeline/{__version__}"},
            follow_redirects=True,
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Exponential backoff with full jitter; honours a numeric Retry-After header."""
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        ceiling = min(self._backoff_base * 2**attempt, MAX_BACKOFF_SECONDS)
        return random.uniform(ceiling / 2, ceiling)  # noqa: S311 - jitter, not crypto

    def get(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        """GET with retries.

        Raises `NotFoundError` on 404 and `ExtractError` once retries are exhausted.
        """
        last_error: str = ""
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            retry_after: str | None = None
            try:
                response = self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 404:
                    raise NotFoundError(f"GET {url} returned 404")
                if response.status_code not in RETRYABLE_STATUS:
                    if response.is_error:
                        raise ExtractError(
                            f"GET {url} failed with HTTP {response.status_code}: "
                            f"{response.text[:300]}"
                        )
                    return response
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")

            if attempt == self._max_retries:
                break
            delay = self.backoff_delay(attempt, retry_after)
            log.warning(
                "request failed, retrying",
                extra={"url": url, "attempt": attempt + 1, "error": last_error, "delay_s": delay},
            )
            self._sleep(delay)

        raise ExtractError(f"GET {url} failed after {self._max_retries + 1} attempts: {last_error}")
