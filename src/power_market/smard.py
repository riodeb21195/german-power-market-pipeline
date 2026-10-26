"""Client for the (unofficial but public) SMARD chart-data API of the Bundesnetzagentur.

The API is two-step: `index_hour.json` lists the start timestamps of all weekly chunks, and each
chunk file holds the hourly values of one week. The newest values of a chunk are `null` until
SMARD publishes them; they are skipped here and picked up by a later run (see lookback window).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from power_market.http import HttpClient
from power_market.schemas import validate_smard_chunk, validate_smard_index

SMARD_BASE_URL = "https://www.smard.de/app/chart_data"
BERLIN = ZoneInfo("Europe/Berlin")
# Upper bound for the newest chunk, which has no successor: one week plus the DST hour.
MAX_CHUNK_SPAN = timedelta(days=7, hours=1)

SeriesKind = Literal["price", "generation", "load"]


@dataclass(frozen=True)
class SmardSeries:
    filter_id: int
    region: str
    slug: str
    kind: SeriesKind
    unit: str


SMARD_SERIES: tuple[SmardSeries, ...] = (
    SmardSeries(4169, "DE-LU", "day_ahead_price", "price", "EUR/MWh"),
    SmardSeries(410, "DE", "grid_load", "load", "MWh"),
    SmardSeries(1223, "DE", "lignite", "generation", "MWh"),
    SmardSeries(1224, "DE", "nuclear", "generation", "MWh"),
    SmardSeries(1225, "DE", "wind_offshore", "generation", "MWh"),
    SmardSeries(1226, "DE", "hydro", "generation", "MWh"),
    SmardSeries(1227, "DE", "other_conventional", "generation", "MWh"),
    SmardSeries(1228, "DE", "other_renewable", "generation", "MWh"),
    SmardSeries(4066, "DE", "biomass", "generation", "MWh"),
    SmardSeries(4067, "DE", "wind_onshore", "generation", "MWh"),
    SmardSeries(4068, "DE", "solar", "generation", "MWh"),
    SmardSeries(4069, "DE", "hard_coal", "generation", "MWh"),
    SmardSeries(4070, "DE", "pumped_storage", "generation", "MWh"),
    SmardSeries(4071, "DE", "natural_gas", "generation", "MWh"),
)


@dataclass(frozen=True)
class SmardRecord:
    ts: datetime
    value: float


@dataclass(frozen=True)
class SmardChunk:
    series: SmardSeries
    chunk_start: datetime
    raw: bytes
    records: list[SmardRecord]
    unpublished: int

    @property
    def source_name(self) -> str:
        return f"smard/{self.series.filter_id}/{self.series.region}"

    @property
    def week_start_local(self) -> date:
        """Monday of the chunk in German local time (the chunk starts 22:00/23:00 UTC Sunday)."""
        return self.chunk_start.astimezone(BERLIN).date()


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _to_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


class SmardClient:
    def __init__(self, http: HttpClient, base_url: str = SMARD_BASE_URL) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def list_chunks(self, series: SmardSeries) -> list[datetime]:
        """Return the sorted start timestamps of all weekly chunks of a series."""
        url = f"{self._base_url}/{series.filter_id}/{series.region}/index_hour.json"
        raw = self._http.get(url).content
        index = validate_smard_index(raw, f"smard index {series.filter_id}/{series.region}")
        return sorted(_from_ms(ms) for ms in index.timestamps)

    def fetch_chunk(self, series: SmardSeries, chunk_start: datetime) -> SmardChunk:
        ms = _to_ms(chunk_start)
        name = f"{series.filter_id}_{series.region}_hour_{ms}.json"
        url = f"{self._base_url}/{series.filter_id}/{series.region}/{name}"
        raw = self._http.get(url).content
        payload = validate_smard_chunk(raw, f"smard chunk {series.filter_id}/{series.region}/{ms}")
        records = [SmardRecord(_from_ms(t), v) for t, v in payload.series if v is not None]
        return SmardChunk(
            series=series,
            chunk_start=chunk_start,
            raw=raw,
            records=records,
            unpublished=len(payload.series) - len(records),
        )

    def fetch_range(
        self, series: SmardSeries, start: datetime, end: datetime
    ) -> Iterator[SmardChunk]:
        """Yield every chunk that overlaps the half-open interval [start, end).

        Whole chunks are returned (not trimmed to the window): re-loading a full week is cheap,
        idempotent thanks to the upsert, and picks up SMARD's retroactive corrections.
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        chunks = self.list_chunks(series)
        for i, chunk_start in enumerate(chunks):
            # the newest chunk has no successor; a discontinued series (nuclear) must not
            # pull its last, years-old chunk into every current window
            chunk_end = chunks[i + 1] if i + 1 < len(chunks) else chunk_start + MAX_CHUNK_SPAN
            if chunk_start < end and chunk_end > start:
                yield self.fetch_chunk(series, chunk_start)
