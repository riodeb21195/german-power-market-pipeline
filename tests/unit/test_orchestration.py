from __future__ import annotations

from datetime import UTC, datetime

import pytest

from power_market.orchestration import pipeline_run_id, window_for_run
from power_market.state import Window

START = datetime(2026, 10, 24, 6, tzinfo=UTC)
END = datetime(2026, 10, 25, 6, tzinfo=UTC)


def test_run_id_is_deterministic_per_dag_run() -> None:
    first = pipeline_run_id("power_market_daily", "scheduled__2026-10-25T06:00:00+00:00")
    again = pipeline_run_id("power_market_daily", "scheduled__2026-10-25T06:00:00+00:00")
    other = pipeline_run_id("power_market_daily", "manual__2026-10-25T07:00:00+00:00")
    assert first == again
    assert first != other


def test_scheduled_run_is_incremental() -> None:
    window = window_for_run(
        run_type="scheduled", data_interval_start=START, data_interval_end=END, params={}
    )
    assert window is None


def test_backfill_run_uses_data_interval() -> None:
    window = window_for_run(
        run_type="backfill", data_interval_start=START, data_interval_end=END, params={}
    )
    assert window == Window(START, END)


def test_backfill_without_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="data interval"):
        window_for_run(
            run_type="backfill", data_interval_start=None, data_interval_end=None, params={}
        )


def test_params_override_everything() -> None:
    window = window_for_run(
        run_type="manual",
        data_interval_start=START,
        data_interval_end=END,
        params={"window_start": "2025-01-01", "window_end": "2025-01-31"},
    )
    assert window == Window(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))


def test_single_day_param() -> None:
    window = window_for_run(
        run_type="manual",
        data_interval_start=None,
        data_interval_end=None,
        params={"window_start": "2025-03-30", "window_end": None},
    )
    assert window == Window(datetime(2025, 3, 30, tzinfo=UTC), datetime(2025, 3, 31, tzinfo=UTC))
