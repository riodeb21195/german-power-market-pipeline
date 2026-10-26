"""Pipeline steps per source: extract -> land -> merge -> reconcile -> advance watermark.

One call handles one source (a SMARD series or a weather location), so Airflow can run and
retry sources independently. The CLI runs all of them in sequence.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Literal
from uuid import UUID

import psycopg

from power_market.config import Settings
from power_market.http import HttpClient
from power_market.landing import LandingZone, make_s3_client
from power_market.smard import SMARD_SERIES, SmardClient, SmardSeries
from power_market.state import (
    RunMode,
    RunStats,
    Window,
    advance_watermark,
    get_watermark,
    incremental_window,
    reconcile,
    track_run,
)
from power_market.warehouse import (
    SMARD_TABLE,
    WEATHER_TABLE,
    MergeResult,
    connect,
    ensure_schema,
    merge_rows,
)
from power_market.weather import LOCATIONS, Location, OpenMeteoClient

log = logging.getLogger(__name__)

# Weather backfills are split into slices so the landing zone stays partitioned by date
# and a single request never gets huge.
WEATHER_SLICE_DAYS = 31


def smard_source(series: SmardSeries) -> str:
    return f"smard/{series.filter_id}/{series.region}"


def weather_source(location: Location) -> str:
    return f"open_meteo/{location.slug}"


@dataclass
class SourceResult:
    source: str
    window: Window | None  # None only if the run failed before its window was known
    status: Literal["success", "failed"] = "success"
    stats: RunStats = field(default_factory=RunStats)
    objects_landed: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "status": self.status,
            "window_start": self.window.start.isoformat() if self.window else None,
            "window_end": self.window.end.isoformat() if self.window else None,
            "objects_landed": self.objects_landed,
            "error": self.error,
            **vars(self.stats),
        }


def _add(stats: RunStats, result: MergeResult) -> None:
    stats.rows_extracted += result.received
    stats.rows_inserted += result.inserted
    stats.rows_updated += result.updated
    stats.rows_unchanged += result.unchanged


def backfill_window(start: date, end: date) -> Window:
    """Window covering the whole days start..end (inclusive), in UTC."""
    return Window(
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
    )


def date_slices(start: date, end: date, days: int) -> Iterator[tuple[date, date]]:
    """Split the inclusive range start..end into inclusive slices of at most `days` days."""
    current = start
    while current <= end:
        slice_end = min(current + timedelta(days=days - 1), end)
        yield current, slice_end
        current = slice_end + timedelta(days=1)


class Pipeline:
    def __init__(
        self,
        *,
        conn: psycopg.Connection,
        landing: LandingZone,
        smard: SmardClient,
        weather: OpenMeteoClient,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._conn = conn
        self._landing = landing
        self._smard = smard
        self._weather = weather
        self._settings = settings
        self._clock = clock

    def _window(self, source: str, window: Window | None) -> tuple[RunMode, Window]:
        if window is not None:
            return "backfill", window
        watermark = get_watermark(self._conn, source)
        return "incremental", incremental_window(
            watermark,
            now=self._clock(),
            lookback_days=self._settings.lookback_days,
            initial_start=date.fromisoformat(self._settings.backfill_start_date),
        )

    def run_smard_series(
        self,
        series: SmardSeries,
        *,
        run_id: UUID,
        window: Window | None = None,
        orchestrator_run_id: str | None = None,
    ) -> SourceResult:
        source = smard_source(series)
        mode, window = self._window(source, window)
        result = SourceResult(source, window)
        timestamps: set[datetime] = set()
        with track_run(
            self._conn,
            run_id=run_id,
            source=source,
            mode=mode,
            window=window,
            orchestrator_run_id=orchestrator_run_id,
        ) as stats:
            result.stats = stats
            for chunk in self._smard.fetch_range(series, window.start, window.end):
                landed = self._landing.put(
                    f"smard/{series.filter_id}_{series.region}",
                    chunk.week_start_local,
                    chunk.raw,
                    metadata={"run-id": str(run_id), "source": source},
                )
                result.objects_landed += landed.created
                rows = [
                    (
                        series.filter_id,
                        series.region,
                        r.ts,
                        r.value,
                        chunk.chunk_start,
                        landed.key,
                        run_id,
                    )
                    for r in chunk.records
                ]
                _add(stats, merge_rows(self._conn, SMARD_TABLE, rows))
                timestamps.update(r.ts for r in chunk.records)

            reconcile(
                self._conn,
                run_id=run_id,
                source=source,
                spec=SMARD_TABLE,
                series_filter={"filter_id": series.filter_id, "region": series.region},
                source_timestamps=timestamps,
            )
            if timestamps:
                advance_watermark(self._conn, source, max(timestamps), run_id)
        return result

    def run_weather_location(
        self,
        location: Location,
        *,
        run_id: UUID,
        window: Window | None = None,
        orchestrator_run_id: str | None = None,
    ) -> SourceResult:
        source = weather_source(location)
        mode, window = self._window(source, window)
        result = SourceResult(source, window)
        timestamps: set[datetime] = set()
        last_day = (window.end - timedelta(microseconds=1)).date()
        with track_run(
            self._conn,
            run_id=run_id,
            source=source,
            mode=mode,
            window=window,
            orchestrator_run_id=orchestrator_run_id,
        ) as stats:
            result.stats = stats
            for start, end in date_slices(window.start.date(), last_day, WEATHER_SLICE_DAYS):
                response = self._weather.fetch(location, start, end)
                landed = self._landing.put(
                    f"open_meteo/{location.slug}",
                    start,
                    response.raw,
                    metadata={"run-id": str(run_id), "source": source},
                )
                result.objects_landed += landed.created
                rows = [
                    (
                        location.slug,
                        r.ts,
                        r.temperature_2m,
                        r.wind_speed_100m,
                        r.shortwave_radiation,
                        r.cloud_cover,
                        landed.key,
                        run_id,
                    )
                    for r in response.records
                ]
                _add(stats, merge_rows(self._conn, WEATHER_TABLE, rows))
                timestamps.update(r.ts for r in response.records)

            reconcile(
                self._conn,
                run_id=run_id,
                source=source,
                spec=WEATHER_TABLE,
                series_filter={"location": location.slug},
                source_timestamps=timestamps,
            )
            if timestamps:
                advance_watermark(self._conn, source, max(timestamps), run_id)
        return result

    def run_all(
        self,
        *,
        run_id: UUID | None = None,
        window: Window | None = None,
        series: tuple[SmardSeries, ...] = SMARD_SERIES,
        locations: tuple[Location, ...] = LOCATIONS,
        orchestrator_run_id: str | None = None,
    ) -> list[SourceResult]:
        """Run every source in sequence; a failing source does not stop the others."""
        rid = run_id or uuid.uuid4()
        orch = orchestrator_run_id
        jobs: list[tuple[str, Callable[[], SourceResult]]] = []
        for s in series:
            job = partial(
                self.run_smard_series, s, run_id=rid, window=window, orchestrator_run_id=orch
            )
            jobs.append((smard_source(s), job))
        for loc in locations:
            job = partial(
                self.run_weather_location, loc, run_id=rid, window=window, orchestrator_run_id=orch
            )
            jobs.append((weather_source(loc), job))
        return [self._guarded(source, window, job) for source, job in jobs]

    @staticmethod
    def _guarded(
        source: str, window: Window | None, job: Callable[[], SourceResult]
    ) -> SourceResult:
        try:
            return job()
        except Exception as exc:  # reported in the result and via the CLI exit code
            log.exception("source failed", extra={"source": source})
            return SourceResult(
                source, window, status="failed", error=f"{type(exc).__name__}: {exc}"
            )


@contextmanager
def build_pipeline(settings: Settings) -> Iterator[Pipeline]:
    """Composition root: wire real clients, warehouse connection and landing zone."""
    with (
        HttpClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            backoff_base_seconds=settings.http_backoff_base_seconds,
            rate_limit_per_second=settings.http_rate_limit_per_second,
        ) as http,
        connect(settings) as conn,
    ):
        ensure_schema(conn)
        landing = LandingZone(make_s3_client(settings), settings.minio_bucket)
        landing.ensure_bucket()
        yield Pipeline(
            conn=conn,
            landing=landing,
            smard=SmardClient(http),
            weather=OpenMeteoClient(http),
            settings=settings,
        )
