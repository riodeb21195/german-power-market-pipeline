from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from power_market.schemas import (
    SchemaDriftError,
    validate_open_meteo,
    validate_smard_chunk,
    validate_smard_index,
)

Load = Callable[[str], bytes]
WEATHER = "open_meteo/hamburg_2026-10-20_2026-10-21.json"
CHUNK = "smard/4169_DE-LU_hour_1792360800000.json"


def mutate(raw: bytes, change: Callable[[dict[str, Any]], None]) -> bytes:
    data = json.loads(raw)
    change(data)
    return json.dumps(data).encode()


def test_recorded_payloads_match_expected_schema(fixture_bytes: Load) -> None:
    index = validate_smard_index(fixture_bytes("smard/index_4169_DE-LU_hour.json"), "t")
    assert len(index.timestamps) > 400
    chunk = validate_smard_chunk(fixture_bytes(CHUNK), "t")
    assert chunk.meta_data.version == 1
    weather = validate_open_meteo(fixture_bytes(WEATHER), "t")
    assert len(weather.hourly.time) == 48


def test_unexpected_field_is_drift(fixture_bytes: Load) -> None:
    raw = mutate(fixture_bytes(CHUNK), lambda d: d.update(unit="MWh"))
    with pytest.raises(SchemaDriftError, match="unexpected field 'unit'") as exc:
        validate_smard_chunk(raw, "smard chunk 4169/DE-LU")
    assert exc.value.source == "smard chunk 4169/DE-LU"
    assert "Schema drift detected in smard chunk 4169/DE-LU" in str(exc.value)


def test_missing_field_is_drift(fixture_bytes: Load) -> None:
    raw = mutate(fixture_bytes(CHUNK), lambda d: d.pop("series"))
    with pytest.raises(SchemaDriftError, match="missing field 'series'"):
        validate_smard_chunk(raw, "t")


def test_changed_value_type_is_drift(fixture_bytes: Load) -> None:
    def to_objects(d: dict[str, Any]) -> None:
        d["series"] = [{"ts": t, "value": v} for t, v in d["series"]]

    with pytest.raises(SchemaDriftError, match=r"series\.0"):
        validate_smard_chunk(mutate(fixture_bytes(CHUNK), to_objects), "t")


def test_renamed_index_key_is_drift() -> None:
    with pytest.raises(SchemaDriftError) as exc:
        validate_smard_index(b'{"timestamp": [1, 2]}', "t")
    assert set(exc.value.problems) == {"missing field 'timestamps'", "unexpected field 'timestamp'"}


def test_null_values_are_allowed_in_smard_series() -> None:
    raw = b'{"meta_data": {"version": 1, "created": 1}, "series": [[1, 2.5], [2, null], [3, 7]]}'
    assert validate_smard_chunk(raw, "t").series == [(1, 2.5), (2, None), (3, 7.0)]


def test_unit_change_is_drift(fixture_bytes: Load) -> None:
    raw = mutate(fixture_bytes(WEATHER), lambda d: d["hourly_units"].update(wind_speed_100m="m/s"))
    with pytest.raises(SchemaDriftError, match="hourly_units changed"):
        validate_open_meteo(raw, "t")


def test_non_utc_timezone_is_drift(fixture_bytes: Load) -> None:
    raw = mutate(fixture_bytes(WEATHER), lambda d: d.update(utc_offset_seconds=3600))
    with pytest.raises(SchemaDriftError, match="expected UTC"):
        validate_open_meteo(raw, "t")


def test_hourly_length_mismatch_is_drift(fixture_bytes: Load) -> None:
    raw = mutate(fixture_bytes(WEATHER), lambda d: d["hourly"]["cloud_cover"].pop())
    with pytest.raises(SchemaDriftError, match="differ in length"):
        validate_open_meteo(raw, "t")


def test_new_weather_variable_is_drift(fixture_bytes: Load) -> None:
    def add_variable(d: dict[str, Any]) -> None:
        d["hourly"]["rain"] = [0.0] * 48

    with pytest.raises(SchemaDriftError, match=r"unexpected field 'hourly\.rain'"):
        validate_open_meteo(mutate(fixture_bytes(WEATHER), add_variable), "t")


def test_invalid_json_is_drift() -> None:
    with pytest.raises(SchemaDriftError):
        validate_smard_index(b"<html>maintenance</html>", "t")
