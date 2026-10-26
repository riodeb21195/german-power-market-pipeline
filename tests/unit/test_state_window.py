from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from power_market.state import Window, incremental_window

NOW = datetime(2026, 10, 25, 6, tzinfo=UTC)


def test_first_run_starts_at_initial_date() -> None:
    window = incremental_window(None, now=NOW, lookback_days=7, initial_start=date(2023, 1, 1))
    assert window == Window(datetime(2023, 1, 1, tzinfo=UTC), NOW)


def test_lookback_reaches_behind_the_watermark() -> None:
    watermark = datetime(2026, 10, 24, 23, tzinfo=UTC)
    window = incremental_window(watermark, now=NOW, lookback_days=7, initial_start=date(2023, 1, 1))
    assert window.start == watermark - timedelta(days=7)
    assert window.end == NOW


def test_window_rejects_naive_and_empty_ranges() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Window(datetime(2026, 1, 1), NOW)  # noqa: DTZ001
    with pytest.raises(ValueError, match="empty window"):
        Window(NOW, NOW)
