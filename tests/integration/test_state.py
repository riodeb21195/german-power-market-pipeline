from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from power_market.state import (
    ReconciliationError,
    Window,
    advance_watermark,
    get_watermark,
    reconcile,
    track_run,
)
from power_market.warehouse import SMARD_TABLE, merge_rows

T0 = datetime(2026, 10, 19, 0, tzinfo=UTC)
SERIES = {"filter_id": 4169, "region": "DE-LU"}
WINDOW = Window(T0, T0 + timedelta(days=1))


def hours(n: int) -> set[datetime]:
    return {T0 + timedelta(hours=i) for i in range(n)}


def load(conn: psycopg.Connection, timestamps: set[datetime]) -> None:
    run = uuid.uuid4()
    merge_rows(conn, SMARD_TABLE, [(4169, "DE-LU", ts, 1.0, T0, "k", run) for ts in timestamps])


# --- checkpoints -------------------------------------------------------------


def test_watermark_starts_empty_and_advances(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    assert get_watermark(conn, "smard/4169/DE-LU") is None
    advance_watermark(conn, "smard/4169/DE-LU", T0, run)
    assert get_watermark(conn, "smard/4169/DE-LU") == T0


def test_watermark_never_moves_backwards(conn: psycopg.Connection) -> None:
    advance_watermark(conn, "s", T0, uuid.uuid4())
    advance_watermark(conn, "s", T0 - timedelta(days=30), uuid.uuid4())  # e.g. a backfill
    assert get_watermark(conn, "s") == T0


# --- reconciliation ----------------------------------------------------------


def test_reconcile_match_is_recorded(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    load(conn, hours(24))
    result = reconcile(
        conn,
        run_id=run,
        source="smard/4169/DE-LU",
        spec=SMARD_TABLE,
        series_filter=SERIES,
        source_timestamps=hours(24),
    )
    assert result is not None
    assert result.status == "match"
    row = conn.execute(
        "select source_rows, target_rows, status from meta.reconciliation where run_id = %s",
        (run,),
    ).fetchone()
    assert row == (24, 24, "match")


def test_reconcile_mismatch_raises_and_is_recorded(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    load(conn, hours(20))
    with pytest.raises(ReconciliationError, match="source has 24 rows, target has 20"):
        reconcile(
            conn,
            run_id=run,
            source="smard/4169/DE-LU",
            spec=SMARD_TABLE,
            series_filter=SERIES,
            source_timestamps=hours(24),
        )
    row = conn.execute("select status from meta.reconciliation where run_id = %s", (run,))
    assert row.fetchone() == ("mismatch",)


def test_reconcile_ignores_other_series_and_can_warn_only(conn: psycopg.Connection) -> None:
    load(conn, hours(3))
    result = reconcile(
        conn,
        run_id=uuid.uuid4(),
        source="smard/410/DE",
        spec=SMARD_TABLE,
        series_filter={"filter_id": 410, "region": "DE"},
        source_timestamps=hours(3),
        raise_on_mismatch=False,
    )
    assert result is not None
    assert (result.target_rows, result.status) == (0, "mismatch")


def test_reconcile_without_source_rows_is_skipped(conn: psycopg.Connection) -> None:
    assert (
        reconcile(
            conn,
            run_id=uuid.uuid4(),
            source="x",
            spec=SMARD_TABLE,
            series_filter=SERIES,
            source_timestamps=set(),
        )
        is None
    )


def test_rerun_of_reconciliation_overwrites(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    load(conn, hours(5))
    for _ in range(2):
        reconcile(
            conn,
            run_id=run,
            source="s",
            spec=SMARD_TABLE,
            series_filter=SERIES,
            source_timestamps=hours(5),
        )
    row = conn.execute("select count(*) from meta.reconciliation").fetchone()
    assert row == (1,)


# --- run metadata ------------------------------------------------------------


def test_track_run_records_success(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    with track_run(
        conn, run_id=run, source="s", mode="incremental", window=WINDOW, orchestrator_run_id="dag1"
    ) as stats:
        stats.rows_extracted, stats.rows_inserted = 10, 7
    row = conn.execute(
        "select status, rows_extracted, rows_inserted, finished_at is not null, "
        "orchestrator_run_id from meta.pipeline_runs where run_id = %s",
        (run,),
    ).fetchone()
    assert row == ("success", 10, 7, True, "dag1")


def test_track_run_records_failure_and_reraises(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    with (
        pytest.raises(RuntimeError, match="boom"),
        track_run(conn, run_id=run, source="s", mode="backfill", window=WINDOW),
    ):
        raise RuntimeError("boom")
    row = conn.execute(
        "select status, error, mode from meta.pipeline_runs where run_id = %s", (run,)
    ).fetchone()
    assert row == ("failed", "RuntimeError: boom", "backfill")


def test_retry_of_same_run_overwrites_record(conn: psycopg.Connection) -> None:
    run = uuid.uuid4()
    with (
        pytest.raises(ValueError, match="first"),
        track_run(conn, run_id=run, source="s", mode="incremental", window=WINDOW),
    ):
        raise ValueError("first")
    with track_run(conn, run_id=run, source="s", mode="incremental", window=WINDOW):
        pass
    rows = conn.execute("select status, error from meta.pipeline_runs").fetchall()
    assert rows == [("success", None)]
