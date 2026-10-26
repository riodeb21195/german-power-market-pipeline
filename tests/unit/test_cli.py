from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest

from power_market import cli
from power_market.config import Settings
from power_market.pipeline import SourceResult
from power_market.state import Window

WINDOW = Window(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC))


class FakePipeline:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def run_all(self, **kwargs: Any) -> list[SourceResult]:
        self.calls.append(kwargs)
        sources = [f"smard/{s.filter_id}/{s.region}" for s in kwargs["series"]]
        sources += [f"open_meteo/{loc.slug}" for loc in kwargs["locations"]]
        results = [SourceResult(source, WINDOW) for source in sources]
        if self.fail:
            results[0].status, results[0].error = "failed", "boom"
        return results


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakePipeline:
    pipeline = FakePipeline()

    @contextmanager
    def build(settings: Settings) -> Iterator[FakePipeline]:
        yield pipeline

    monkeypatch.setattr(cli, "build_pipeline", build)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    return pipeline


def test_run_all_sources(fake: FakePipeline, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run"]) == 0
    call = fake.calls[0]
    assert call["window"] is None
    assert len(call["series"]) == len(cli.SMARD_SERIES)
    assert len(call["locations"]) == len(cli.LOCATIONS)
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed"] == 0
    assert summary["sources"] == len(cli.SMARD_SERIES) + len(cli.LOCATIONS)


def test_filters_by_source_and_slug(fake: FakePipeline) -> None:
    cli.main(["run", "--source", "weather"])
    assert fake.calls[-1]["series"] == ()
    cli.main(["run", "--only", "solar", "munich"])
    assert [s.slug for s in fake.calls[-1]["series"]] == ["solar"]
    assert [loc.slug for loc in fake.calls[-1]["locations"]] == ["munich"]


def test_backfill_passes_window_and_ids(fake: FakePipeline) -> None:
    run_id = uuid.uuid4()
    code = cli.main(
        [
            "backfill",
            "--start",
            "2026-10-01",
            "--end",
            "2026-10-03",
            "--run-id",
            str(run_id),
            "--orchestrator-run-id",
            "scheduled__2026-10-03",
        ]
    )
    assert code == 0
    call = fake.calls[0]
    assert call["window"] == Window(
        datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 4, tzinfo=UTC)
    )
    assert call["run_id"] == run_id
    assert call["orchestrator_run_id"] == "scheduled__2026-10-03"


def test_backfill_defaults_end_to_today(fake: FakePipeline) -> None:
    cli.main(["backfill", "--start", "2026-01-01"])
    assert fake.calls[0]["window"].end.date() > date.today()  # noqa: DTZ011


def test_backfill_rejects_reversed_range(
    fake: FakePipeline, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["backfill", "--start", "2026-10-03", "--end", "2026-10-01"]) == 2
    assert "must not be before" in capsys.readouterr().err
    assert fake.calls == []


def test_failed_source_gives_exit_code_1(
    fake: FakePipeline, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.fail = True
    assert cli.main(["run"]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1


def test_unknown_slug_is_rejected(fake: FakePipeline) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--only", "atlantis"])


def test_module_entry_point_shows_help() -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "power_market", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "backfill" in completed.stdout
