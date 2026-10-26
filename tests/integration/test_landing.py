from __future__ import annotations

from datetime import date

from power_market.landing import LandingZone, landing_key

DAY = date(2026, 10, 19)


def test_payload_is_stored_byte_for_byte(landing: LandingZone) -> None:
    payload = b'{"series": [[1, null]]}'  # no trailing newline, odd spacing kept
    obj = landing.put("smard/4169_DE-LU", DAY, payload, metadata={"run-id": "r1"})
    assert obj.created
    assert obj.key.startswith("smard/4169_DE-LU/date=2026-10-19/")
    assert landing.get(obj.key) == payload


def test_identical_payload_is_not_duplicated(landing: LandingZone) -> None:
    first = landing.put("smard/x", DAY, b"{}")
    second = landing.put("smard/x", DAY, b"{}")
    assert first.key == second.key
    assert (first.created, second.created) == (True, False)
    assert landing.list_keys("smard/x") == [first.key]


def test_corrected_payload_lands_as_new_object(landing: LandingZone) -> None:
    landing.put("smard/x", DAY, b'{"v": 1}')
    landing.put("smard/x", DAY, b'{"v": 2}')
    assert len(landing.list_keys("smard/x/date=2026-10-19/")) == 2


def test_ensure_bucket_is_idempotent(landing: LandingZone) -> None:
    landing.ensure_bucket()
    landing.ensure_bucket()


def test_landing_key_is_deterministic() -> None:
    assert landing_key("a/", DAY, b"x") == landing_key("a", DAY, b"x")
    assert landing_key("a", DAY, b"x") != landing_key("a", DAY, b"y")
