from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from power_market.warehouse import SMARD_TABLE, WEATHER_TABLE, ensure_schema, merge_rows

T0 = datetime(2026, 10, 19, 0, tzinfo=UTC)
RUN = uuid.uuid4()


def smard_rows(
    values: list[float], run: uuid.UUID = RUN, key: str = "k1"
) -> list[tuple[object, ...]]:
    return [(4169, "DE-LU", T0 + timedelta(hours=i), v, T0, key, run) for i, v in enumerate(values)]


def count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(f"select count(*) from {table}").fetchone()  # noqa: S608 - test constant
    assert row is not None
    return int(row[0])


def test_ensure_schema_is_idempotent(conn: psycopg.Connection) -> None:
    ensure_schema(conn)
    ensure_schema(conn)
    assert count(conn, "raw.smard_timeseries") == 0


def test_first_load_inserts_everything(conn: psycopg.Connection) -> None:
    result = merge_rows(conn, SMARD_TABLE, smard_rows([1.0, 2.0, 3.0]))
    assert (result.inserted, result.updated, result.unchanged) == (3, 0, 0)
    assert count(conn, "raw.smard_timeseries") == 3


def test_rerun_with_same_data_changes_nothing(conn: psycopg.Connection) -> None:
    merge_rows(conn, SMARD_TABLE, smard_rows([1.0, 2.0, 3.0]))
    before = conn.execute("select max(loaded_at) from raw.smard_timeseries").fetchone()

    # new run id and landing key, identical data -> no row is touched
    result = merge_rows(conn, SMARD_TABLE, smard_rows([1.0, 2.0, 3.0], uuid.uuid4(), "k2"))

    assert (result.inserted, result.updated, result.unchanged) == (0, 0, 3)
    assert count(conn, "raw.smard_timeseries") == 3
    after = conn.execute("select max(loaded_at) from raw.smard_timeseries").fetchone()
    assert before == after


def test_corrected_values_are_updated(conn: psycopg.Connection) -> None:
    merge_rows(conn, SMARD_TABLE, smard_rows([1.0, 2.0, 3.0]))
    new_run = uuid.uuid4()
    result = merge_rows(conn, SMARD_TABLE, smard_rows([1.0, 2.5, 3.0], new_run, "k2"))

    assert (result.inserted, result.updated, result.unchanged) == (0, 1, 2)
    row = conn.execute(
        "select value, landing_key, run_id from raw.smard_timeseries where ts = %s",
        (T0 + timedelta(hours=1),),
    ).fetchone()
    assert row == (2.5, "k2", new_run)


def test_duplicates_in_batch_keep_last_occurrence(conn: psycopg.Connection) -> None:
    rows = [*smard_rows([1.0, 2.0]), (4169, "DE-LU", T0, 9.0, T0, "k1", RUN)]
    result = merge_rows(conn, SMARD_TABLE, rows)

    assert (result.received, result.distinct, result.duplicates) == (3, 2, 1)
    row = conn.execute("select value from raw.smard_timeseries where ts = %s", (T0,)).fetchone()
    assert row == (9.0,)


def test_empty_batch_is_a_noop(conn: psycopg.Connection) -> None:
    result = merge_rows(conn, SMARD_TABLE, [])
    assert (result.received, result.inserted) == (0, 0)


def test_null_weather_values_compare_as_unchanged(conn: psycopg.Connection) -> None:
    rows = [("hamburg", T0, 10.5, None, 0.0, 80.0, "k1", RUN)]
    merge_rows(conn, WEATHER_TABLE, rows)
    again = merge_rows(conn, WEATHER_TABLE, rows)
    assert again.unchanged == 1  # NULL vs NULL is not a change (IS DISTINCT FROM)

    filled = merge_rows(conn, WEATHER_TABLE, [("hamburg", T0, 10.5, 30.2, 0.0, 80.0, "k2", RUN)])
    assert filled.updated == 1


def test_failed_merge_rolls_back(conn: psycopg.Connection) -> None:
    merge_rows(conn, SMARD_TABLE, smard_rows([1.0]))
    bad = [*smard_rows([5.0, 6.0]), (4169, "DE-LU", T0, None, T0, "k", RUN)]  # NOT NULL violated
    with pytest.raises(psycopg.errors.NotNullViolation):
        merge_rows(conn, SMARD_TABLE, bad)
    rows = conn.execute("select value from raw.smard_timeseries order by ts").fetchall()
    assert rows == [(1.0,)]
