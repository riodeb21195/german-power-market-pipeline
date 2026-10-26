"""Load the committed one-week sample of real raw data into the warehouse.

Used by CI (`dbt build` without calling the live APIs) and for a quick local demo:

    uv run python scripts/load_sample_data.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from psycopg import sql

from power_market.config import get_settings
from power_market.log import configure_logging
from power_market.warehouse import SMARD_TABLE, WEATHER_TABLE, TableSpec, connect, ensure_schema

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "warehouse"
log = logging.getLogger("load_sample_data")


def load(spec: TableSpec, csv_path: Path) -> int:
    settings = get_settings()
    with connect(settings) as conn:
        ensure_schema(conn)
        target = sql.Identifier(spec.schema, spec.table)
        columns = sql.SQL(", ").join(sql.Identifier(c) for c in spec.columns)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(sql.SQL("truncate {}").format(target))
            copy = sql.SQL("copy {} ({}) from stdin with (format csv, header true)")
            with cur.copy(copy.format(target, columns)) as stream, csv_path.open("rb") as f:
                while chunk := f.read(65536):
                    stream.write(chunk)
            cur.execute(sql.SQL("select count(*) from {}").format(target))
            row = cur.fetchone()
    count = int(row[0]) if row else 0
    log.info("sample loaded", extra={"table": f"{spec.schema}.{spec.table}", "rows": count})
    return count


def main() -> None:
    configure_logging(get_settings().log_level)
    load(SMARD_TABLE, SAMPLE_DIR / "smard_timeseries.csv")
    load(WEATHER_TABLE, SAMPLE_DIR / "weather_hourly.csv")


if __name__ == "__main__":
    main()
