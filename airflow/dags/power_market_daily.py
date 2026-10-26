"""
### power_market_daily

Daily batch for the question *when is power in Germany cheapest and greenest, and what role
does the weather play?*

1. **extract_load_smard** / **extract_load_weather** - one mapped task per SMARD series and per
   weather location: extract (retry, rate limit, schema-drift check) -> land raw JSON in the
   landing zone -> COPY + MERGE into `raw.*` -> reconcile row counts -> advance watermark.
2. **dbt_source_freshness** - fails if new data stopped arriving (error after 54 h).
3. **dbt_build** - seeds, SCD2 snapshot, models and tests on the `prod` target.

**Windows**: scheduled runs are incremental (watermark minus `LOOKBACK_DAYS`). Backfill runs
(`airflow backfill create --dag-id power_market_daily --from-date ... --to-date ...`) load
their data interval. A manual run with the params `window_start` / `window_end` reloads that
date range. Every variant is idempotent.

**Alerts**: a task that failed after its last retry, and a failed DAG run, which includes a run
that exceeds `dagrun_timeout`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Param, dag, task
from airflow.timetables.interval import CronDataIntervalTimetable

from power_market.alerting import dag_failure_callback, task_failure_callback
from power_market.smard import SMARD_SERIES
from power_market.weather import LOCATIONS

DAG_ID = "power_market_daily"
# keep the dbt invocation identical everywhere; target/log paths outside the baked-in project
DBT = (
    "cd $DBT_PROJECT_DIR && $DBT_BIN {command} --target prod "
    "--target-path /tmp/dbt/target --log-path /tmp/dbt/logs"
)

default_args: dict[str, Any] = {
    "owner": "data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
    "execution_timeout": timedelta(minutes=45),
    "on_failure_callback": task_failure_callback,
}


def _run_source(kind: str, slug: str) -> dict[str, object]:
    # heavy imports inside the task keep DAG parsing fast
    from airflow.sdk import get_current_context

    from power_market.config import get_settings
    from power_market.log import configure_logging
    from power_market.orchestration import pipeline_run_id, window_for_run
    from power_market.pipeline import build_pipeline

    settings = get_settings()
    configure_logging(settings.log_level)
    context = get_current_context()
    dag_run = context["dag_run"]
    run_type = getattr(dag_run.run_type, "value", str(dag_run.run_type))
    window = window_for_run(
        run_type=run_type,
        data_interval_start=context.get("data_interval_start"),
        data_interval_end=context.get("data_interval_end"),
        params=context["params"],
    )
    options: dict[str, Any] = {
        "run_id": pipeline_run_id(DAG_ID, dag_run.run_id),
        "window": window,
        "orchestrator_run_id": dag_run.run_id,
    }
    with build_pipeline(settings) as pipeline:
        if kind == "smard":
            series = next(s for s in SMARD_SERIES if s.slug == slug)
            result = pipeline.run_smard_series(series, **options)
        else:
            location = next(loc for loc in LOCATIONS if loc.slug == slug)
            result = pipeline.run_weather_location(location, **options)
    return result.as_dict()


@dag(
    dag_id=DAG_ID,
    doc_md=__doc__,
    # 06:00 UTC: yesterday's SMARD values are mostly published, today's day-ahead prices too
    schedule=CronDataIntervalTimetable("0 6 * * *", timezone="UTC"),
    start_date=datetime(2026, 10, 20, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    dagrun_timeout=timedelta(hours=2),
    on_failure_callback=dag_failure_callback,
    params={
        "window_start": Param(
            None, type=["null", "string"], format="date", description="reload from (YYYY-MM-DD)"
        ),
        "window_end": Param(
            None, type=["null", "string"], format="date", description="reload to, inclusive"
        ),
    },
    tags=["power-market", "batch", "dbt"],
)
def power_market_daily() -> None:
    @task(max_active_tis_per_dag=3)
    def extract_load_smard(series_slug: str) -> dict[str, object]:
        """Extract one SMARD series and load it into raw.smard_timeseries."""
        return _run_source("smard", series_slug)

    @task(max_active_tis_per_dag=3)
    def extract_load_weather(location_slug: str) -> dict[str, object]:
        """Extract one weather location and load it into raw.weather_hourly."""
        return _run_source("weather", location_slug)

    smard = extract_load_smard.expand(series_slug=[s.slug for s in SMARD_SERIES])
    weather = extract_load_weather.expand(location_slug=[loc.slug for loc in LOCATIONS])

    freshness = BashOperator(
        task_id="dbt_source_freshness",
        bash_command=DBT.format(command="source freshness"),
        retries=0,
    )
    build = BashOperator(
        task_id="dbt_build",
        bash_command=DBT.format(command="build"),
        retries=1,
    )

    [smard, weather] >> freshness >> build


power_market_daily()
