from datetime import UTC, datetime

import time_machine

from ocmanager.core.clock import utcnow


def test_utcnow_is_aware_utc() -> None:
    assert utcnow().tzinfo is UTC


def test_utcnow_follows_time_machine() -> None:
    with time_machine.travel(datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC), tick=False):
        assert utcnow() == datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
