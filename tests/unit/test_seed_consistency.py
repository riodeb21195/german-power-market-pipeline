"""The dbt seeds describe the same series and locations as the Python extractor."""

from __future__ import annotations

import csv
from pathlib import Path

from power_market.smard import SMARD_SERIES
from power_market.weather import LOCATIONS

SEEDS = Path(__file__).parents[2] / "dbt" / "seeds"


def read_seed(name: str) -> list[dict[str, str]]:
    with (SEEDS / f"{name}.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_smard_series_seed_matches_extractor() -> None:
    seed = {
        (int(r["smard_filter_id"]), r["region"], r["series_slug"], r["kind"], r["unit"])
        for r in read_seed("smard_series")
    }
    python = {(s.filter_id, s.region, s.slug, s.kind, s.unit) for s in SMARD_SERIES}
    assert seed == python


def test_every_generation_series_is_classified() -> None:
    rows = read_seed("smard_series")
    assert all(r["category"] and r["is_renewable"] for r in rows if r["kind"] == "generation")
    assert not any(r["category"] for r in rows if r["kind"] != "generation")


def test_weather_locations_seed_matches_extractor() -> None:
    seed = {
        (r["location_slug"], r["location_name"], float(r["latitude"]), float(r["longitude"]))
        for r in read_seed("weather_locations")
    }
    python = {(loc.slug, loc.name, loc.latitude, loc.longitude) for loc in LOCATIONS}
    assert seed == python
