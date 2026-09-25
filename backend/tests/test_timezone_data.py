"""Windows has no IANA time zone database; without the tzdata package every
command-practice request with the browser's time zone was rejected with 422
(owner's laptop 25.09.2026, `PUT .../draft` 422 on each start).
https://docs.python.org/3/library/zoneinfo.html#data-sources"""

from __future__ import annotations

import importlib.util
from zoneinfo import ZoneInfo

import pytest

from cyber_range_coach.schemas import CommandDraftRequest


def test_tzdata_is_installed_for_platforms_without_a_system_database() -> None:
    assert importlib.util.find_spec("tzdata") is not None


@pytest.mark.parametrize("zone", ["Asia/Almaty", "Asia/Qostanay", "Europe/Moscow", "UTC"])
def test_browser_time_zones_are_accepted(zone: str) -> None:
    ZoneInfo(zone)
    draft = CommandDraftRequest.model_validate(
        {"technique_id": "linux-grep-text-pattern", "shell": "bash", "timezone": zone, "answer": ""}
    )
    assert draft.timezone == zone
