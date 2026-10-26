"""End-to-end pipeline runs against real Postgres + S3, with the HTTP APIs faked."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from power_market.config import Settings
from power_market.http import HttpClient, RateLimiter
from power_market.landing import LandingZone
from power_market.pipeline import Pipeline, backfill_window
from power_market.smard import SmardClient, SmardSeries
from power_market.weather import LOCATIONS, OpenMeteoClient

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
WEEK1 = datetime(2026, 10, 11, 22, tzinfo=UTC)  # Mon 2026-10-12 00:00 Berlin
WEEK2 = datetime(2026, 10, 18, 22, tzinfo=UTC)  # Mon 2026-10-19 00:00 Berlin (169 h)
PRICE = SmardSeries(4169, "DE-LU", "day_ahead_price", "price", "EUR/MWh")
LOAD = SmardSeries(410, "DE", "grid_load", "load", "MWh")
HAMBURG = next(loc for loc in LOCATIONS if loc.slug == "hamburg")


def ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def week(start: datetime, hours: int, base: float) -> dict[str, object]:
    series = [[ms(start + timedelta(hours=h)), base + h] for h in range(hours)]
    series[-1][1] = None  # newest hour not yet published  # type: ignore[call-overload]
    return {"meta_data": {"version": 1, "created": 0}, "series": series}


@dataclass
class FakeApis:
    """Serves SMARD chunks and Open-Meteo responses; tests mutate it to simulate changes."""

    chunks: dict[int, dict[datetime, dict[str, object]]] = field(default_factory=dict)
    failing_filters: set[int] = field(default_factory=set)
    weather: bytes = (FIXTURES / "open_meteo/hamburg_2026-10-20_2026-10-21.json").read_bytes()
    weather_requests: list[httpx.QueryParams] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "archive-api.open-meteo.com":
            self.weather_requests.append(request.url.params)
            return httpx.Response(200, content=self.weather)
        filter_id = int(request.url.path.split("/")[3])
        if filter_id in self.failing_filters:
            return httpx.Response(503)
        chunks = self.chunks[filter_id]
        if request.url.path.endswith("index_hour.json"):
            return httpx.Response(200, json={"timestamps": [ms(c) for c in chunks]})
        for start, payload in chunks.items():
            if request.url.path.endswith(f"_hour_{ms(start)}.json"):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)


@pytest.fixture
def apis() -> FakeApis:
    return FakeApis(
        chunks={
            4169: {WEEK1: week(WEEK1, 168, 50.0), WEEK2: week(WEEK2, 169, 80.0)},
            410: {WEEK1: week(WEEK1, 168, 40_000.0), WEEK2: week(WEEK2, 169, 41_000.0)},
        }
    )


@pytest.fixture
def make_pipeline(
    conn: psycopg.Connection, landing: LandingZone, settings: Settings, apis: FakeApis
) -> Callable[[], Pipeline]:
    def build() -> Pipeline:
        http = HttpClient(
            max_retries=1,
            transport=httpx.MockTransport(apis),
            sleep=lambda _: None,
            rate_limiter=RateLimiter(1000, sleep=lambda _: None),
        )
        return Pipeline(
            conn=conn,
            landing=landing,
            smard=SmardClient(http),
            weather=OpenMeteoClient(http, today=lambda: NOW.date()),
            settings=settings.model_copy(
                update={"backfill_start_date": "2026-10-12", "lookback_days": 7}
            ),
            clock=lambda: NOW,
        )

    return build


def run(pipeline: Pipeline, **kwargs: object) -> dict[str, dict[str, object]]:
    results = pipeline.run_all(series=(PRICE, LOAD), locations=(HAMBURG,), **kwargs)  # type: ignore[arg-type]
    return {r.source: r.as_dict() for r in results}


def scalar(conn: psycopg.Connection, query: str) -> object:
    row = conn.execute(query).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return row[0]


def test_first_run_loads_lands_and_records_everything(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, landing: LandingZone
) -> None:
    results = run(make_pipeline())

    assert {r["status"] for r in results.values()} == {"success"}
    price = results["smard/4169/DE-LU"]
    assert price["rows_extracted"] == 167 + 168  # the null hour of each week is skipped
    assert price["rows_inserted"] == 335
    assert price["objects_landed"] == 2
    assert results["open_meteo/hamburg"]["rows_inserted"] == 48

    assert scalar(conn, "select count(*) from raw.smard_timeseries") == 2 * 335
    assert scalar(conn, "select count(*) from meta.pipeline_runs where status = 'success'") == 3
    assert scalar(conn, "select count(*) from meta.reconciliation where status = 'match'") == 3
    watermark = scalar(
        conn, "select watermark from meta.checkpoints where source = 'smard/4169/DE-LU'"
    )
    assert watermark == WEEK2 + timedelta(hours=167)

    keys = landing.list_keys("smard/4169_DE-LU/")
    assert [k.split("/")[2] for k in keys] == ["date=2026-10-12", "date=2026-10-19"]


def test_repeating_the_same_run_is_idempotent(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, landing: LandingZone
) -> None:
    """The 'DAG run executed twice' case: same window, no new rows, no new raw objects."""
    window = backfill_window(date(2026, 10, 12), date(2026, 10, 25))
    run(make_pipeline(), window=window)
    objects_before = landing.list_keys()

    results = run(make_pipeline(), window=window)

    for result in results.values():
        assert (result["rows_inserted"], result["rows_updated"]) == (0, 0)
        assert result["objects_landed"] == 0
    assert landing.list_keys() == objects_before
    assert scalar(conn, "select count(*) from raw.smard_timeseries") == 2 * 335


def test_next_incremental_run_adds_no_rows_without_new_data(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection
) -> None:
    run(make_pipeline())
    results = run(make_pipeline())

    for result in results.values():
        assert (result["rows_inserted"], result["rows_updated"]) == (0, 0)
    # SMARD weeks are the same objects; weather requests a shifted range (a new raw response)
    assert results["smard/4169/DE-LU"]["objects_landed"] == 0
    assert scalar(conn, "select count(*) from raw.weather_hourly") == 48


def test_late_correction_and_new_hour_are_picked_up(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, apis: FakeApis
) -> None:
    run(make_pipeline())
    series = apis.chunks[4169][WEEK2]["series"]
    assert isinstance(series, list)
    series[10][1] = 999.0  # SMARD corrects an old value
    series[-1][1] = 1.0  # and publishes the missing hour

    result = run(make_pipeline())["smard/4169/DE-LU"]

    assert (result["rows_inserted"], result["rows_updated"]) == (1, 1)
    assert result["objects_landed"] == 1  # corrected payload kept as a new raw object
    value = scalar(
        conn,
        f"select value from raw.smard_timeseries where filter_id = 4169 "  # noqa: S608
        f"and ts = '{(WEEK2 + timedelta(hours=10)).isoformat()}'",
    )
    assert value == 999.0


def test_incremental_window_uses_watermark_and_lookback(
    make_pipeline: Callable[[], Pipeline], apis: FakeApis
) -> None:
    run(make_pipeline())
    results = run(make_pipeline())

    window_start = datetime.fromisoformat(str(results["smard/4169/DE-LU"]["window_start"]))
    assert window_start == WEEK2 + timedelta(hours=167) - timedelta(days=7)
    # weather: watermark 2026-10-21 23:00 minus 7 days
    assert apis.weather_requests[-1]["start_date"] == "2026-10-14"


def test_failing_source_does_not_stop_others(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, apis: FakeApis
) -> None:
    apis.failing_filters.add(410)

    results = run(make_pipeline())

    assert results["smard/410/DE"]["status"] == "failed"
    assert "after 2 attempts: HTTP 503" in str(results["smard/410/DE"]["error"])
    assert results["smard/4169/DE-LU"]["status"] == "success"
    assert results["open_meteo/hamburg"]["status"] == "success"
    row = conn.execute(
        "select status, error from meta.pipeline_runs where source = 'smard/410/DE'"
    ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert scalar(conn, "select count(*) from meta.checkpoints where source = 'smard/410/DE'") == 0


def test_schema_drift_stops_the_source_without_loading(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, apis: FakeApis
) -> None:
    apis.chunks[4169][WEEK2]["unit"] = "EUR/MWh"  # new, unexpected field

    results = run(make_pipeline())

    price = results["smard/4169/DE-LU"]
    assert price["status"] == "failed"
    assert "SchemaDriftError" in str(price["error"])
    assert "unexpected field 'unit'" in str(price["error"])
    assert scalar(conn, "select count(*) from raw.smard_timeseries where filter_id = 4169") == 167


def test_backfill_window_is_explicit_and_keeps_watermark(
    make_pipeline: Callable[[], Pipeline], conn: psycopg.Connection, apis: FakeApis
) -> None:
    run(make_pipeline())
    run_id = uuid.uuid4()

    results = run(
        make_pipeline(),
        run_id=run_id,
        window=backfill_window(date(2026, 10, 12), date(2026, 10, 13)),
    )

    assert set(apis.weather_requests[-1].items()) >= {
        ("start_date", "2026-10-12"),
        ("end_date", "2026-10-13"),
    }
    assert results["smard/4169/DE-LU"]["rows_extracted"] == 167  # only the first week overlaps
    modes = conn.execute(
        "select distinct mode from meta.pipeline_runs where run_id = %s", (run_id,)
    ).fetchall()
    assert modes == [("backfill",)]
    watermark = scalar(
        conn, "select watermark from meta.checkpoints where source = 'smard/4169/DE-LU'"
    )
    assert watermark == WEEK2 + timedelta(hours=167)  # not moved backwards


def test_weather_payload_from_fixture_is_stored_unchanged(
    make_pipeline: Callable[[], Pipeline], landing: LandingZone, apis: FakeApis
) -> None:
    run(make_pipeline())
    (key,) = landing.list_keys("open_meteo/hamburg/")
    assert landing.get(key) == apis.weather
    assert json.loads(landing.get(key))["latitude"] == pytest.approx(53.55, abs=0.05)


def test_build_pipeline_wires_real_dependencies(settings: Settings) -> None:
    from power_market.pipeline import build_pipeline

    with build_pipeline(settings) as pipeline:
        assert pipeline.run_all(series=(), locations=()) == []
