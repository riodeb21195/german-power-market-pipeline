"""Validate raw payloads against the expected source schemas to detect schema drift.

Every payload is validated *before* it is landed or loaded. Any deviation (missing or
unexpected fields, changed types or changed units) raises `SchemaDriftError`, which stops the
pipeline with a readable message instead of loading silently wrong data.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from power_market.http import ExtractError

# Units we rely on downstream. A unit change (e.g. km/h -> m/s) is drift, too.
OPEN_METEO_EXPECTED_UNITS: dict[str, str] = {
    "time": "iso8601",
    "temperature_2m": "°C",
    "wind_speed_100m": "km/h",
    "shortwave_radiation": "W/m²",
    "cloud_cover": "%",
}


class SchemaDriftError(ExtractError):
    """The payload does not match the expected schema."""

    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"Schema drift detected in {source}: " + "; ".join(problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SmardIndex(_Strict):
    timestamps: list[int]


class SmardMeta(_Strict):
    version: int
    created: int


class SmardChunkPayload(_Strict):
    meta_data: SmardMeta
    series: list[tuple[int, float | None]]


class OpenMeteoHourly(_Strict):
    time: list[str]
    temperature_2m: list[float | None]
    wind_speed_100m: list[float | None]
    shortwave_radiation: list[float | None]
    cloud_cover: list[float | None]

    @model_validator(mode="after")
    def _equal_lengths(self) -> Self:
        lengths = {name: len(values) for name, values in self}
        if len(set(lengths.values())) > 1:
            raise ValueError(f"hourly arrays differ in length: {lengths}")
        return self


class OpenMeteoPayload(_Strict):
    latitude: float
    longitude: float
    generationtime_ms: float
    utc_offset_seconds: int
    timezone: str
    timezone_abbreviation: str
    elevation: float
    hourly_units: dict[str, str]
    hourly: OpenMeteoHourly

    @model_validator(mode="after")
    def _units_and_timezone(self) -> Self:
        if self.hourly_units != OPEN_METEO_EXPECTED_UNITS:
            expected = OPEN_METEO_EXPECTED_UNITS
            raise ValueError(f"hourly_units changed: expected {expected}, got {self.hourly_units}")
        if self.utc_offset_seconds != 0:
            raise ValueError(f"expected UTC timestamps, got offset {self.utc_offset_seconds}s")
        return self


def _format(exc: ValidationError) -> list[str]:
    problems = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        if err["type"] == "extra_forbidden":
            problems.append(f"unexpected field '{location}'")
        elif err["type"] == "missing":
            problems.append(f"missing field '{location}'")
        else:
            problems.append(f"{location}: {err['msg']}")
    return problems


def _validate[M: BaseModel](model: type[M], raw: bytes, source: str) -> M:
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise SchemaDriftError(source, _format(exc)) from exc


def validate_smard_index(raw: bytes, source: str) -> SmardIndex:
    return _validate(SmardIndex, raw, source)


def validate_smard_chunk(raw: bytes, source: str) -> SmardChunkPayload:
    return _validate(SmardChunkPayload, raw, source)


def validate_open_meteo(raw: bytes, source: str) -> OpenMeteoPayload:
    return _validate(OpenMeteoPayload, raw, source)
