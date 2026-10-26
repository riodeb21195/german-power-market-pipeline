from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pytest

from power_market.http import HttpClient
from power_market.schemas import SchemaDriftError
from power_market.weather import LOCATIONS, Location, OpenMeteoClient, _today_utc

MakeHttp = Callable[[Callable[[httpx.Request], httpx.Response]], HttpClient]
Load = Callable[[str], bytes]
HAMBURG = next(loc for loc in LOCATIONS if loc.slug == "hamburg")
FIXTURE = "open_meteo/hamburg_2026-10-20_2026-10-21.json"


def capture(body: bytes, seen: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body)

    return handler


def client(http: HttpClient, today: date = date(2026, 10, 25)) -> OpenMeteoClient:
    return OpenMeteoClient(http, today=lambda: today)


def test_locations_are_unique_and_in_germany() -> None:
    assert len({loc.slug for loc in LOCATIONS}) == len(LOCATIONS)
    for loc in LOCATIONS:
        assert 47 < loc.latitude < 55.1
        assert 5.8 < loc.longitude < 15.1


def test_fetch_parses_records(make_http: MakeHttp, fixture_bytes: Load) -> None:
    seen: list[httpx.Request] = []
    raw = fixture_bytes(FIXTURE)
    response = client(make_http(capture(raw, seen))).fetch(
        HAMBURG, date(2026, 10, 20), date(2026, 10, 21)
    )

    assert len(response.records) == 48
    first = response.records[0]
    assert first.ts == datetime(2026, 10, 20, 0, tzinfo=UTC)
    expected = json.loads(raw)["hourly"]
    assert first.temperature_2m == expected["temperature_2m"][0]
    assert first.cloud_cover == expected["cloud_cover"][0]
    assert response.raw == raw
    assert response.source_name == "open_meteo/hamburg"

    params = seen[0].url.params
    assert params["timezone"] == "UTC"
    assert params["start_date"] == "2026-10-20"
    assert params["hourly"] == "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover"
    assert float(params["latitude"]) == HAMBURG.latitude


def test_end_date_is_capped_at_today(make_http: MakeHttp, fixture_bytes: Load) -> None:
    seen: list[httpx.Request] = []
    response = client(make_http(capture(fixture_bytes(FIXTURE), seen))).fetch(
        HAMBURG, date(2026, 10, 20), date(2026, 12, 31)
    )
    assert seen[0].url.params["end_date"] == "2026-10-25"
    assert response.end_date == date(2026, 10, 25)


def test_start_after_end_is_rejected(make_http: MakeHttp) -> None:
    with pytest.raises(ValueError, match="after end_date"):
        client(make_http(capture(b"", []))).fetch(HAMBURG, date(2026, 10, 30), date(2026, 10, 31))


def test_hours_without_values_are_dropped(make_http: MakeHttp, fixture_bytes: Load) -> None:
    data = json.loads(fixture_bytes(FIXTURE))
    for variable in ("temperature_2m", "wind_speed_100m", "shortwave_radiation", "cloud_cover"):
        data["hourly"][variable][-1] = None
    data["hourly"]["cloud_cover"][0] = None  # partially filled hour is kept
    response = client(make_http(capture(json.dumps(data).encode(), []))).fetch(
        HAMBURG, date(2026, 10, 20), date(2026, 10, 21)
    )
    assert len(response.records) == 47
    assert response.records[0].cloud_cover is None


def test_drift_is_raised(make_http: MakeHttp) -> None:
    body = b'{"error": true, "reason": "unexpected"}'
    with pytest.raises(SchemaDriftError):
        client(make_http(capture(body, []))).fetch(HAMBURG, date(2026, 10, 20), date(2026, 10, 21))


def test_location_is_hashable() -> None:
    assert len({HAMBURG, Location("x", "X", 50.0, 10.0, "test")}) == 2


def test_default_today_is_utc_date() -> None:
    assert _today_utc() == datetime.now(tz=UTC).date()
