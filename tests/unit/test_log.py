from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator

import pytest

from power_market.log import JsonFormatter, configure_logging


@pytest.fixture
def clean_root() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    root.handlers = []
    yield root
    root.handlers, root.level = saved


def test_extra_fields_become_json_keys() -> None:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": "loaded"})
    record.run_id, record.rows = "abc", 42
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "loaded"
    assert (payload["run_id"], payload["rows"]) == ("abc", 42)
    assert payload["ts"].endswith("+00:00")


def test_exception_is_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc_info"]


def test_configure_logging_twice_adds_one_handler(clean_root: logging.Logger) -> None:
    configure_logging("debug")
    configure_logging("debug")
    ours = [h for h in clean_root.handlers if isinstance(h.formatter, JsonFormatter)]
    assert len(ours) == 1
    assert clean_root.level == logging.DEBUG


def test_logs_go_to_stderr(clean_root: logging.Logger, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logging.getLogger("power_market.test").info("hello", extra={"source": "smard"})
    out, err = capsys.readouterr()
    assert out == ""
    assert json.loads(err)["source"] == "smard"
