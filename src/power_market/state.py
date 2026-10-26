"""Pipeline state in the `meta` schema: watermarks, run log and row-count reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql

from power_market.warehouse import TableSpec

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Window:
    """Half-open extraction interval [start, end) in UTC."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.start >= self.end:
            raise ValueError(f"empty window: {self.start} >= {self.end}")


def get_watermark(conn: psycopg.Connection, source: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("select watermark from meta.checkpoints where source = %s", (source,))
        row = cur.fetchone()
    return row[0] if row else None


def advance_watermark(
    conn: psycopg.Connection, source: str, watermark: datetime, run_id: UUID
) -> None:
    """Move the watermark forward. It never moves backwards, so a backfill of an old range
    cannot make the next incremental run re-extract everything since then."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.checkpoints (source, watermark, last_run_id)
            values (%s, %s, %s)
            on conflict (source) do update set
                watermark = greatest(meta.checkpoints.watermark, excluded.watermark),
                last_run_id = excluded.last_run_id,
                updated_at = now()
            """,
            (source, watermark, run_id),
        )


def incremental_window(
    watermark: datetime | None,
    *,
    now: datetime,
    lookback_days: int,
    initial_start: date,
) -> Window:
    """Window for the next incremental run.

    Starts `lookback_days` before the watermark to re-load late corrections; without a
    watermark (first run) it starts at `initial_start`.
    """
    if watermark is None:
        start = datetime.combine(initial_start, time.min, tzinfo=UTC)
    else:
        start = watermark - timedelta(days=lookback_days)
    return Window(start=start, end=now)


RunMode = Literal["incremental", "backfill"]


@dataclass
class RunStats:
    rows_extracted: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0


@contextmanager
def track_run(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    source: str,
    mode: RunMode,
    window: Window,
    orchestrator_run_id: str | None = None,
) -> Iterator[RunStats]:
    """Record a run as `running`, then `success` or `failed` (with the error message).

    Re-running the same run id overwrites the previous record instead of adding a duplicate.
    Requires an autocommit connection so the status survives a failed load transaction.
    """
    stats = RunStats()
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.pipeline_runs
                (run_id, source, mode, window_start, window_end, status, orchestrator_run_id)
            values (%s, %s, %s, %s, %s, 'running', %s)
            on conflict (run_id, source) do update set
                mode = excluded.mode,
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                status = 'running',
                error = null,
                orchestrator_run_id = excluded.orchestrator_run_id,
                started_at = now(),
                finished_at = null
            """,
            (run_id, source, mode, window.start, window.end, orchestrator_run_id),
        )
    try:
        yield stats
    except Exception as exc:
        _finish(conn, run_id, source, "failed", stats, f"{type(exc).__name__}: {exc}")
        log.error("run failed", extra={"run_id": str(run_id), "source": source, "error": str(exc)})
        raise
    _finish(conn, run_id, source, "success", stats, None)
    log.info("run succeeded", extra={"run_id": str(run_id), "source": source, **vars(stats)})


def _finish(
    conn: psycopg.Connection,
    run_id: UUID,
    source: str,
    status: Literal["success", "failed"],
    stats: RunStats,
    error: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update meta.pipeline_runs set
                status = %s, error = %s, finished_at = now(),
                rows_extracted = %s, rows_inserted = %s, rows_updated = %s, rows_unchanged = %s
            where run_id = %s and source = %s
            """,
            (
                status,
                error,
                stats.rows_extracted,
                stats.rows_inserted,
                stats.rows_updated,
                stats.rows_unchanged,
                run_id,
                source,
            ),
        )


class ReconciliationError(Exception):
    """Source and target row counts differ."""


@dataclass(frozen=True)
class ReconciliationResult:
    source: str
    window_start: datetime
    window_end: datetime
    source_rows: int
    target_rows: int

    @property
    def status(self) -> Literal["match", "mismatch"]:
        return "match" if self.source_rows == self.target_rows else "mismatch"


def reconcile(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    source: str,
    spec: TableSpec,
    series_filter: Mapping[str, Any],
    source_timestamps: set[datetime],
    raise_on_mismatch: bool = True,
) -> ReconciliationResult | None:
    """Check that every distinct source hour of a series exists exactly once in the target.

    The window is [min, max] of the source timestamps. Rows the target holds in that window but
    the source no longer delivers (e.g. a value SMARD withdrew) also show up as a mismatch.
    The result is stored in `meta.reconciliation` either way.
    """
    if not source_timestamps:
        return None
    window_start, window_end = min(source_timestamps), max(source_timestamps)
    conditions: list[sql.Composable] = [
        sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder(column))
        for column in series_filter
    ]
    conditions.append(sql.SQL("ts between %(window_start)s and %(window_end)s"))
    query = sql.SQL("select count(*) from {} where {}").format(
        sql.Identifier(spec.schema, spec.table), sql.SQL(" and ").join(conditions)
    )
    params = {**series_filter, "window_start": window_start, "window_end": window_end}

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        target_rows = int(row[0]) if row else 0
        result = ReconciliationResult(
            source, window_start, window_end, len(source_timestamps), target_rows
        )
        cur.execute(
            """
            insert into meta.reconciliation
                (run_id, source, window_start, window_end, source_rows, target_rows, status)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, source) do update set
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                source_rows = excluded.source_rows,
                target_rows = excluded.target_rows,
                status = excluded.status,
                checked_at = now()
            """,
            (
                run_id,
                source,
                window_start,
                window_end,
                result.source_rows,
                target_rows,
                result.status,
            ),
        )

    extra = {
        "source": source,
        "source_rows": result.source_rows,
        "target_rows": result.target_rows,
        "status": result.status,
    }
    if result.status == "mismatch":
        log.error("reconciliation mismatch", extra=extra)
        if raise_on_mismatch:
            raise ReconciliationError(
                f"{source}: source has {result.source_rows} rows, target has {target_rows} "
                f"between {window_start.isoformat()} and {window_end.isoformat()}"
            )
    else:
        log.info("reconciliation ok", extra=extra)
    return result
