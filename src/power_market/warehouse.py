"""Warehouse access: connection, schema bootstrap and the COPY + MERGE upsert."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import psycopg
from psycopg import sql

from power_market.config import Settings

log = logging.getLogger(__name__)

# serialises concurrent schema bootstraps (parallel Airflow tasks)
_SCHEMA_LOCK_ID = 7_242_001


def connect(settings: Settings) -> psycopg.Connection:
    """Autocommit connection; atomic units use explicit `conn.transaction()` blocks."""
    return psycopg.connect(settings.warehouse_dsn, application_name="power_market", autocommit=True)


def ensure_schema(conn: psycopg.Connection) -> None:
    ddl = files("power_market.sql").joinpath("schema.sql").read_text(encoding="utf-8")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
        cur.execute(ddl.encode())


@dataclass(frozen=True)
class TableSpec:
    """Describes a raw table for the generic merge.

    Only `data_columns` decide whether an existing row is updated. Lineage columns
    (`meta_columns`, e.g. landing key and run id) are refreshed together with the data but a
    re-run with identical data leaves the row untouched.
    """

    schema: str
    table: str
    key_columns: tuple[str, ...]
    data_columns: tuple[str, ...]
    meta_columns: tuple[str, ...]
    types: dict[str, str]

    @property
    def columns(self) -> tuple[str, ...]:
        return self.key_columns + self.data_columns + self.meta_columns


SMARD_TABLE = TableSpec(
    schema="raw",
    table="smard_timeseries",
    key_columns=("filter_id", "region", "ts"),
    data_columns=("value",),
    meta_columns=("chunk_start", "landing_key", "run_id"),
    types={
        "filter_id": "integer",
        "region": "text",
        "ts": "timestamptz",
        "value": "double precision",
        "chunk_start": "timestamptz",
        "landing_key": "text",
        "run_id": "uuid",
    },
)

WEATHER_TABLE = TableSpec(
    schema="raw",
    table="weather_hourly",
    key_columns=("location", "ts"),
    data_columns=("temperature_2m", "wind_speed_100m", "shortwave_radiation", "cloud_cover"),
    meta_columns=("landing_key", "run_id"),
    types={
        "location": "text",
        "ts": "timestamptz",
        "temperature_2m": "double precision",
        "wind_speed_100m": "double precision",
        "shortwave_radiation": "double precision",
        "cloud_cover": "double precision",
        "landing_key": "text",
        "run_id": "uuid",
    },
)


@dataclass(frozen=True)
class MergeResult:
    received: int  # rows handed to the loader
    distinct: int  # rows after in-batch deduplication
    inserted: int
    updated: int

    @property
    def unchanged(self) -> int:
        return self.distinct - self.inserted - self.updated

    @property
    def duplicates(self) -> int:
        return self.received - self.distinct


def _ids(names: Sequence[str], prefix: str | None = None) -> sql.Composed:
    if prefix is None:
        return sql.SQL(", ").join(sql.Identifier(n) for n in names)
    return sql.SQL(", ").join(sql.Identifier(prefix, n) for n in names)


def merge_rows(
    conn: psycopg.Connection, spec: TableSpec, rows: Iterable[Sequence[Any]]
) -> MergeResult:
    """Upsert `rows` (values in `spec.columns` order) in one transaction.

    1. COPY all rows into a temporary staging table (fast bulk load).
    2. Deduplicate by natural key, the last occurrence in the batch wins.
    3. MERGE into the target: insert new keys, update keys whose data changed.
    """
    target = sql.Identifier(spec.schema, spec.table)
    stage, dedup = sql.Identifier("_stage"), sql.Identifier("_dedup")
    column_defs = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(spec.types[c])) for c in spec.columns
    )
    keys = spec.key_columns
    join = sql.SQL(" and ").join(
        sql.SQL("{} = {}").format(sql.Identifier("t", k), sql.Identifier("s", k)) for k in keys
    )
    changed = sql.SQL("({}) is distinct from ({})").format(
        _ids(spec.data_columns, "t"), _ids(spec.data_columns, "s")
    )
    update_cols = spec.data_columns + spec.meta_columns
    set_clause = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Identifier("s", c)) for c in update_cols
    )

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            sql.SQL("create temp table {} ({}, _seq bigint) on commit drop").format(
                stage, column_defs
            )
        )
        received = 0
        copy_stmt = sql.SQL("copy {} ({}, _seq) from stdin").format(stage, _ids(spec.columns))
        with cur.copy(copy_stmt) as copy:
            for row in rows:
                copy.write_row((*row, received))
                received += 1

        cur.execute(
            sql.SQL(
                "create temp table {dedup} on commit drop as "
                "select distinct on ({keys}) {cols} from {stage} order by {keys}, _seq desc"
            ).format(dedup=dedup, keys=_ids(keys), cols=_ids(spec.columns), stage=stage)
        )
        distinct = cur.rowcount

        cur.execute(
            sql.SQL(
                "merge into {target} as t using {dedup} as s on {join} "
                "when matched and {changed} then update set {set_clause}, loaded_at = now() "
                "when not matched then insert ({cols}) values ({values}) "
                "returning merge_action()"
            ).format(
                target=target,
                dedup=dedup,
                join=join,
                changed=changed,
                set_clause=set_clause,
                cols=_ids(spec.columns),
                values=_ids(spec.columns, "s"),
            )
        )
        actions = [action for (action,) in cur.fetchall()]

    result = MergeResult(
        received=received,
        distinct=distinct,
        inserted=actions.count("INSERT"),
        updated=actions.count("UPDATE"),
    )
    log.info(
        "merged rows",
        extra={
            "table": f"{spec.schema}.{spec.table}",
            "received": result.received,
            "duplicates": result.duplicates,
            "inserted": result.inserted,
            "updated": result.updated,
            "unchanged": result.unchanged,
        },
    )
    return result
