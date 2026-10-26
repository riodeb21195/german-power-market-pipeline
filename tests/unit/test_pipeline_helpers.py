from __future__ import annotations

from datetime import UTC, date, datetime

from power_market.pipeline import SourceResult, backfill_window, date_slices


def test_backfill_window_covers_whole_days() -> None:
    window = backfill_window(date(2026, 10, 1), date(2026, 10, 3))
    assert window.start == datetime(2026, 10, 1, tzinfo=UTC)
    assert window.end == datetime(2026, 10, 4, tzinfo=UTC)


def test_date_slices_split_inclusive_ranges() -> None:
    slices = list(date_slices(date(2026, 1, 1), date(2026, 3, 5), days=31))
    assert slices == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 3, 3)),
        (date(2026, 3, 4), date(2026, 3, 5)),
    ]
    assert list(date_slices(date(2026, 1, 1), date(2026, 1, 1), days=31)) == [
        (date(2026, 1, 1), date(2026, 1, 1))
    ]


def test_failed_result_without_window_serialises() -> None:
    result = SourceResult("smard/1/DE", None, status="failed", error="boom")
    payload = result.as_dict()
    assert payload["window_start"] is None
    assert payload["status"] == "failed"
    assert payload["rows_extracted"] == 0
