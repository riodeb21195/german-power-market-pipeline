"""Orchestrator-facing helpers, kept free of Airflow imports so they are unit-testable."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from power_market.pipeline import backfill_window
from power_market.state import Window


def pipeline_run_id(dag_id: str, orchestrator_run_id: str) -> uuid.UUID:
    """Deterministic run id: a retried or cleared DAG run updates its existing metadata rows."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"airflow/{dag_id}/{orchestrator_run_id}")


def window_for_run(
    *,
    run_type: str,
    data_interval_start: datetime | None,
    data_interval_end: datetime | None,
    params: Mapping[str, Any],
) -> Window | None:
    """Decide which window a DAG run extracts.

    - Manual run with `window_start` (and optional `window_end`) params: that date range.
    - Backfill run (`airflow backfill create ...`): the run's data interval.
    - Scheduled or plain manual run: None, i.e. incremental from the watermarks.
    """
    start_param = params.get("window_start")
    if start_param:
        start = date.fromisoformat(str(start_param))
        end_param = params.get("window_end")
        end = date.fromisoformat(str(end_param)) if end_param else start
        return backfill_window(start, end)
    if run_type == "backfill":
        if data_interval_start is None or data_interval_end is None:
            raise ValueError("backfill run without a data interval")
        return Window(data_interval_start, data_interval_end)
    return None
