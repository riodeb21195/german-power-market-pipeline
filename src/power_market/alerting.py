"""Alerts to a Slack incoming webhook or only to the log, plus the Airflow failure callbacks.

Sending never raises: a broken alert channel must not hide the original failure.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from power_market.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    title: str
    message: str
    link: str | None = None


def send_alert(alert: Alert, settings: Settings | None = None) -> bool:
    """Log the alert and post it to Slack if configured. Returns True if it was delivered."""
    settings = settings or get_settings()
    # title and message go into the log text itself: Airflow 3 drops `extra` fields
    log.error("alert via %s: %s | %s", settings.alert_channel, alert.title, alert.message)
    if settings.alert_channel == "log":
        return True
    try:
        url = settings.slack_webhook_url.get_secret_value()
        if not url:
            raise ValueError("ALERT_CHANNEL=slack but SLACK_WEBHOOK_URL is empty")
        text = f"*{alert.title}*\n{alert.message}"
        if alert.link:
            text += f"\n<{alert.link}|Open in Airflow>"
        httpx.post(url, json={"text": text}, timeout=10).raise_for_status()
    except Exception as exc:
        log.exception("alert delivery failed: %s", exc)
        return False
    return True


def _task_label(context: Mapping[str, Any]) -> tuple[str, str]:
    ti = context.get("ti")
    dag_run = context.get("dag_run")
    dag_id = getattr(ti, "dag_id", None) or getattr(dag_run, "dag_id", "unknown dag")
    task_id = getattr(ti, "task_id", None)
    map_index = getattr(ti, "map_index", -1)
    if task_id is not None and map_index is not None and map_index >= 0:
        task_id = f"{task_id}[{map_index}]"
    run_id = getattr(dag_run, "run_id", None) or context.get("run_id", "?")
    return (f"{dag_id}.{task_id}" if task_id else str(dag_id)), str(run_id)


def task_failure_callback(context: Mapping[str, Any]) -> None:
    """Airflow `on_failure_callback` for tasks: runs once all retries are used up."""
    where, run_id = _task_label(context)
    exception = context.get("exception")
    ti = context.get("ti")
    send_alert(
        Alert(
            title=f"Task failed: {where}",
            message=f"run {run_id}, attempt {getattr(ti, 'try_number', '?')}: "
            f"{type(exception).__name__}: {exception}",
            link=getattr(ti, "log_url", None),
        )
    )


def dag_failure_callback(context: Mapping[str, Any]) -> None:
    """Airflow `on_failure_callback` for the DAG, also called when `dagrun_timeout` is hit."""
    where, run_id = _task_label(context)
    dag_id = where.partition(".")[0]
    reason = context.get("reason") or "one or more tasks failed"
    send_alert(Alert(title=f"DAG run failed: {dag_id}", message=f"run {run_id}: {reason}"))
