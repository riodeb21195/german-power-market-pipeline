from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from power_market.http import HttpClient
from power_market.schemas import SchemaDriftError
from power_market.smard import SMARD_SERIES, SmardClient, SmardSeries

MakeHttp = Callable[[Callable[[httpx.Request], httpx.Response]], HttpClient]
Load = Callable[[str], bytes]

PRICE = SmardSeries(4169, "DE-LU", "day_ahead_price", "price", "EUR/MWh")
WIND = SmardSeries(4067, "DE", "wind_onshore", "generation", "MWh")
# Monday 2026-10-19 00:00 Europe/Berlin; this week contains the DST switch (169 hours)
DST_WEEK = datetime(2026, 10, 18, 22, tzinfo=UTC)


def serve(
    files: dict[str, bytes], requested: list[str] | None = None
) -> Callable[..., httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if requested is not None:
            requested.append(request.url.path)
        for suffix, body in files.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, content=body)
        return httpx.Response(404)

    return handler


def test_series_catalogue_is_unique() -> None:
    keys = [(s.filter_id, s.region) for s in SMARD_SERIES]
    assert len(keys) == len(set(keys))
    assert {s.slug for s in SMARD_SERIES} >= {"day_ahead_price", "grid_load", "solar"}


def test_list_chunks_returns_sorted_utc_timestamps(
    make_http: MakeHttp, fixture_bytes: Load
) -> None:
    raw = fixture_bytes("smard/index_4169_DE-LU_hour.json")
    client = SmardClient(make_http(serve({"4169/DE-LU/index_hour.json": raw})))
    chunks = client.list_chunks(PRICE)
    assert chunks == sorted(chunks)
    assert chunks[0] == datetime(2018, 9, 30, 22, tzinfo=UTC)
    assert all(c.tzinfo is UTC for c in chunks)


def test_fetch_chunk_skips_unpublished_values(make_http: MakeHttp, fixture_bytes: Load) -> None:
    raw = fixture_bytes("smard/4067_DE_hour_1792360800000.json")
    client = SmardClient(make_http(serve({"4067_DE_hour_1792360800000.json": raw})))
    chunk = client.fetch_chunk(WIND, datetime(2026, 10, 18, 22, tzinfo=UTC))

    total = len(json.loads(raw)["series"])
    assert total == 169  # DST week: one extra hour
    assert chunk.unpublished > 0
    assert len(chunk.records) + chunk.unpublished == total
    assert chunk.raw == raw  # raw bytes are kept unchanged for the landing zone
    assert chunk.records[0].ts == DST_WEEK
    assert chunk.source_name == "smard/4067/DE"
    assert chunk.week_start_local.isoformat() == "2026-10-19"
    # hourly spacing in UTC, even across the DST switch
    deltas = {b.ts - a.ts for a, b in zip(chunk.records, chunk.records[1:], strict=False)}
    assert deltas == {timedelta(hours=1)}


def test_fetch_chunk_raises_on_drift(make_http: MakeHttp) -> None:
    body = b'{"meta_data": {"version": 2}, "series": []}'
    client = SmardClient(make_http(serve({".json": body})))
    with pytest.raises(SchemaDriftError, match=r"meta_data\.created"):
        client.fetch_chunk(PRICE, DST_WEEK)


def _index(*starts: datetime) -> bytes:
    return json.dumps({"timestamps": [int(s.timestamp() * 1000) for s in starts]}).encode()


def _chunk(start: datetime) -> bytes:
    ms = int(start.timestamp() * 1000)
    return json.dumps({"meta_data": {"version": 1, "created": 0}, "series": [[ms, 1.0]]}).encode()


def test_fetch_range_selects_overlapping_chunks(make_http: MakeHttp) -> None:
    week = timedelta(days=7)
    w0, w1, w2, w3 = (DST_WEEK - 3 * week + i * week for i in range(4))
    files = {"index_hour.json": _index(w2, w0, w3, w1)}
    files |= {f"_hour_{int(w.timestamp() * 1000)}.json": _chunk(w) for w in (w0, w1, w2, w3)}
    requested: list[str] = []
    client = SmardClient(make_http(serve(files, requested)))

    # window starts mid-w1 and ends exactly at the start of w3 (half-open)
    chunks = list(client.fetch_range(PRICE, w1 + timedelta(days=3), w3))
    assert [c.chunk_start for c in chunks] == [w1, w2]

    # the newest chunk has no successor and is included when the window reaches it
    latest = list(client.fetch_range(PRICE, w3 + timedelta(days=1), w3 + timedelta(days=2)))
    assert [c.chunk_start for c in latest] == [w3]
    # ...but not once the window lies more than a week after its start (discontinued series)
    stale = list(client.fetch_range(PRICE, w3 + timedelta(days=30), w3 + timedelta(days=31)))
    assert stale == []
    assert sum(path.endswith("index_hour.json") for path in requested) == 3


def test_fetch_range_requires_aware_datetimes(make_http: MakeHttp) -> None:
    client = SmardClient(make_http(serve({})))
    with pytest.raises(ValueError, match="timezone-aware"):
        list(client.fetch_range(PRICE, datetime(2026, 1, 1), datetime(2026, 1, 2)))  # noqa: DTZ001
