from __future__ import annotations

import pytest
from pydantic import ValidationError

from power_market.config import Settings, get_settings


def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAREHOUSE_HOST", raising=False)
    s = settings()
    assert s.warehouse_host == "localhost"
    assert s.alert_channel == "log"
    assert s.lookback_days == 7


def test_environment_overrides_and_secret_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_HOST", "db")
    monkeypatch.setenv("WAREHOUSE_PASSWORD", "s3cret")
    s = settings()
    assert s.warehouse_host == "db"
    assert "password=s3cret" in s.warehouse_dsn
    assert "s3cret" not in repr(s)


def test_invalid_alert_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_CHANNEL", "pager")
    with pytest.raises(ValidationError):
        settings()


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
