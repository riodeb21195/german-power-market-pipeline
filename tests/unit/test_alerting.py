from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from power_market import alerting
from power_market.alerting import (
    Alert,
    dag_failure_callback,
    send_alert,
    task_failure_callback,
)
from power_market.config import Settings

ALERT = Alert("DAG failed", "extract_load_smard: HTTP 503", link="http://x/log")


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_log_channel_only_logs(caplog: pytest.LogCaptureFixture) -> None:
    assert send_alert(ALERT, settings())
    assert caplog.messages == ["alert via log: DAG failed | extract_load_smard: HTTP 503"]


def test_slack_message(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, str], timeout: float) -> httpx.Response:
        posted.append({"url": url, **json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerting.httpx, "post", fake_post)
    cfg = settings(alert_channel="slack", slack_webhook_url=SecretStr("https://hooks.test/x"))
    assert send_alert(ALERT, cfg)
    assert posted[0]["url"] == "https://hooks.test/x"
    assert posted[0]["text"].startswith("*DAG failed*")
    assert "<http://x/log|Open in Airflow>" in posted[0]["text"]


def test_slack_errors_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_post(url: str, json: dict[str, str], timeout: float) -> httpx.Response:
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerting.httpx, "post", failing_post)
    cfg = settings(alert_channel="slack", slack_webhook_url=SecretStr("https://hooks.test/x"))
    assert send_alert(ALERT, cfg) is False
    assert send_alert(ALERT, settings(alert_channel="slack")) is False  # no webhook configured


@dataclass
class FakeTI:
    dag_id: str = "power_market_daily"
    task_id: str = "extract_load_smard"
    map_index: int = 3
    try_number: int = 4
    log_url: str = "http://localhost:8080/log"


@dataclass
class FakeDagRun:
    dag_id: str = "power_market_daily"
    run_id: str = "scheduled__2026-10-25T06:00:00+00:00"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Alert]:
    alerts: list[Alert] = []
    monkeypatch.setattr(alerting, "send_alert", lambda alert: alerts.append(alert))
    return alerts


def test_task_failure_callback(sent: list[Alert]) -> None:
    task_failure_callback(
        {"ti": FakeTI(), "dag_run": FakeDagRun(), "exception": RuntimeError("HTTP 503")}
    )
    assert sent[0].title == "Task failed: power_market_daily.extract_load_smard[3]"
    assert "attempt 4: RuntimeError: HTTP 503" in sent[0].message
    assert sent[0].link == "http://localhost:8080/log"


def test_dag_failure_callback(sent: list[Alert]) -> None:
    dag_failure_callback({"dag_run": FakeDagRun(), "reason": "timed_out"})
    assert sent[0].title == "DAG run failed: power_market_daily"
    assert sent[0].message.endswith("timed_out")
    dag_failure_callback({"ti": FakeTI(map_index=-1), "dag_run": FakeDagRun()})
    assert sent[1].message.endswith("one or more tasks failed")
