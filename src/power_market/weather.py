"""Client for the Open-Meteo historical weather (archive) API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from power_market.http import HttpClient
from power_market.schemas import validate_open_meteo

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "wind_speed_100m",
    "shortwave_radiation",
    "cloud_cover",
)


@dataclass(frozen=True)
class Location:
    slug: str
    name: str
    latitude: float
    longitude: float
    rationale: str


# Coordinates from the Open-Meteo geocoding API: North Sea wind, solar in the south and the
# large load centres.
LOCATIONS: tuple[Location, ...] = (
    Location("husum", "Husum", 54.4858, 9.05239, "North Sea coast, onshore wind"),
    Location("hamburg", "Hamburg", 53.55073, 9.99302, "Northern Germany, wind and load"),
    Location("berlin", "Berlin", 52.52437, 13.41053, "Eastern Germany, load centre"),
    Location("cologne", "Cologne", 50.93333, 6.95, "Rhine-Ruhr, largest load centre"),
    Location("frankfurt", "Frankfurt am Main", 50.11552, 8.68417, "Central Germany"),
    Location("munich", "Munich", 48.13743, 11.57549, "Southern Germany, high solar output"),
)


@dataclass(frozen=True)
class WeatherRecord:
    ts: datetime
    temperature_2m: float | None
    wind_speed_100m: float | None
    shortwave_radiation: float | None
    cloud_cover: float | None


@dataclass(frozen=True)
class WeatherResponse:
    location: Location
    start_date: date
    end_date: date
    raw: bytes
    records: list[WeatherRecord]

    @property
    def source_name(self) -> str:
        return f"open_meteo/{self.location.slug}"


def _today_utc() -> date:
    return datetime.now(tz=UTC).date()


class OpenMeteoClient:
    def __init__(
        self,
        http: HttpClient,
        base_url: str = OPEN_METEO_ARCHIVE_URL,
        today: Callable[[], date] = _today_utc,
    ) -> None:
        self._http = http
        self._base_url = base_url
        self._today = today

    def fetch(self, location: Location, start_date: date, end_date: date) -> WeatherResponse:
        """Fetch hourly weather for [start_date, end_date] (inclusive, UTC).

        The archive rejects end dates in the future, so `end_date` is capped at today.
        Hours without any value yet are dropped and filled by a later run.
        """
        end_date = min(end_date, self._today())
        if start_date > end_date:
            raise ValueError(f"start_date {start_date} is after end_date {end_date}")
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "hourly": ",".join(WEATHER_VARIABLES),
            "timezone": "UTC",
        }
        raw = self._http.get(self._base_url, params=params).content
        hourly = validate_open_meteo(raw, f"open_meteo {location.slug}").hourly
        records = [
            WeatherRecord(datetime.fromisoformat(t).replace(tzinfo=UTC), *values)
            for t, *values in zip(
                hourly.time,
                hourly.temperature_2m,
                hourly.wind_speed_100m,
                hourly.shortwave_radiation,
                hourly.cloud_cover,
                strict=True,
            )
            if any(v is not None for v in values)
        ]
        return WeatherResponse(location, start_date, end_date, raw, records)
