"""DAG import and structure check, run inside the Airflow image (CI and `make dag-check`).

    docker run --rm --entrypoint python <image> /opt/airflow/tests/check_dags.py

Exits non-zero on import errors or if the DAG structure drifts from what the pipeline expects.
"""

from __future__ import annotations

import sys

from airflow.dag_processing.dagbag import DagBag


def main() -> int:
    bag = DagBag(dag_folder="/opt/airflow/dags")
    problems: list[str] = [
        f"import error in {path}: {err}" for path, err in bag.import_errors.items()
    ]

    dag = bag.dags.get("power_market_daily")
    if dag is None:
        problems.append("DAG power_market_daily not found")
    else:
        tasks = {t.task_id: t for t in dag.tasks}
        expected = {
            "extract_load_smard",
            "extract_load_weather",
            "dbt_source_freshness",
            "dbt_build",
        }
        if set(tasks) != expected:
            problems.append(f"unexpected tasks: {sorted(tasks)}")
        else:
            if tasks["dbt_source_freshness"].upstream_task_ids != {
                "extract_load_smard",
                "extract_load_weather",
            }:
                problems.append("freshness must wait for both extract tasks")
            if tasks["dbt_build"].upstream_task_ids != {"dbt_source_freshness"}:
                problems.append("dbt_build must run after freshness")
            for task_id in ("extract_load_smard", "extract_load_weather"):
                task = tasks[task_id]
                if task.retries < 1 or task.on_failure_callback is None:
                    problems.append(f"{task_id} needs retries and a failure callback")
        if dag.catchup:
            problems.append("catchup must be off (backfills are explicit)")
        if dag.dagrun_timeout is None or dag.on_failure_callback is None:
            problems.append("DAG needs a dagrun_timeout and a failure callback")
        if dag.max_active_runs != 1:
            problems.append("max_active_runs must be 1 (runs share watermarks)")

    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        print(f"OK: {len(bag.dags)} DAG(s) imported, structure as expected")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
