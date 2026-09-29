import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.config import Settings
from ocmanager.nodes import registry, traffic
from ocmanager.nodes.models import SessionLog, TrafficDaily, TrafficSample
from ocmanager.nodes.occtl.parser import OcSession
from ocmanager.nodes.traffic import SessionEnd, counter_delta

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)


def oc(
    username: str = "c1-d1",
    bytes_in: int = 0,
    bytes_out: int = 0,
    *,
    sid: str = "7",
    connected: datetime = T0,
) -> OcSession:
    return OcSession(
        sid, username, "203.0.113.1", "10.77.0.2", bytes_in, bytes_out, connected, None
    )


@pytest.fixture
async def node_id(session: AsyncSession, settings: Settings) -> int:
    return (await registry.ensure_local_node(session, settings)).id


async def samples(session: AsyncSession) -> list[tuple[int, int, int]]:
    rows = await session.scalars(select(TrafficSample).order_by(TrafficSample.id))
    return [(r.bytes_in_delta, r.bytes_out_delta, r.duration_sec) for r in rows]


async def daily(session: AsyncSession) -> dict[str, tuple[int, int]]:
    rows = await session.scalars(select(TrafficDaily).order_by(TrafficDaily.day))
    return {f"{r.username}@{r.day}": (r.bytes_in, r.bytes_out) for r in rows}


# --- counter_delta ---------------------------------------------------------


@pytest.mark.parametrize(
    ("prev", "current", "expected"),
    [(0, 0, 0), (100, 150, 50), (150, 20, 20), (5, 5, 0), (0, 700, 700)],
)
def test_counter_delta(prev: int, current: int, expected: int) -> None:
    assert counter_delta(prev, current) == expected


# --- collect ---------------------------------------------------------------


async def test_first_poll_counts_everything_the_session_has_moved(
    session: AsyncSession, node_id: int
) -> None:
    result = await traffic.collect(session, node_id, [oc(bytes_in=1000, bytes_out=2000)], T0 + MIN)
    assert (result.seen, result.opened, result.closed) == (1, 1, 0)
    assert (result.bytes_in, result.bytes_out) == (1000, 2000)
    assert result.usernames == {"c1-d1"}
    assert await samples(session) == [(1000, 2000, 60)]  # 60 c от connected_at
    assert await daily(session) == {"c1-d1@2026-09-22": (1000, 2000)}


async def test_next_polls_count_only_the_increment(session: AsyncSession, node_id: int) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=1000, bytes_out=2000)], T0 + MIN)
    result = await traffic.collect(
        session, node_id, [oc(bytes_in=1500, bytes_out=2600)], T0 + 6 * MIN
    )
    assert (result.opened, result.bytes_in, result.bytes_out) == (0, 500, 600)
    assert await samples(session) == [(1000, 2000, 60), (500, 600, 300)]
    assert await daily(session) == {"c1-d1@2026-09-22": (1500, 2600)}


async def test_idle_poll_writes_no_sample(session: AsyncSession, node_id: int) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=10)], T0 + MIN)
    await traffic.collect(session, node_id, [oc(bytes_in=10)], T0 + 6 * MIN)
    assert len(await samples(session)) == 1


async def test_counter_reset_inside_one_session_id_is_treated_as_a_restart(
    session: AsyncSession, node_id: int
) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=150)], T0 + MIN)
    await traffic.collect(session, node_id, [oc(bytes_in=20)], T0 + 6 * MIN)
    assert [s[0] for s in await samples(session)] == [150, 20]


async def test_vanished_session_is_closed(session: AsyncSession, node_id: int) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=10)], T0 + MIN)
    result = await traffic.collect(session, node_id, [], T0 + 6 * MIN)
    assert (result.seen, result.closed) == (0, 1)
    assert result.usernames == {"c1-d1"}  # финальные счётчики придут хуком; пользователь «затронут»
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert (log.ended_at, log.final_received) == (T0 + 6 * MIN, False)
    again = await traffic.collect(session, node_id, [], T0 + 11 * MIN)
    assert again.closed == 0


async def test_same_session_id_with_another_start_time_is_a_new_session(
    session: AsyncSession, node_id: int
) -> None:
    """ocserv перезапустили — ID начались заново. Счётчики новой сессии не вычитаются из старой."""
    await traffic.collect(session, node_id, [oc(bytes_in=900, sid="1")], T0 + MIN)
    restarted = oc(bytes_in=40, sid="1", connected=T0 + 5 * MIN)
    result = await traffic.collect(session, node_id, [restarted], T0 + 6 * MIN)
    assert (result.opened, result.closed) == (1, 1)
    assert await session.scalar(select(func.count()).select_from(SessionLog)) == 2
    assert [s[0] for s in await samples(session)] == [900, 40]


async def test_two_users_are_tracked_separately(session: AsyncSession, node_id: int) -> None:
    both = [oc("c1-d1", 10, sid="1"), oc("c2-d1", 30, sid="2")]
    result = await traffic.collect(session, node_id, both, T0 + MIN)
    assert result.usernames == {"c1-d1", "c2-d1"}
    assert await daily(session) == {"c1-d1@2026-09-22": (10, 0), "c2-d1@2026-09-22": (30, 0)}


async def test_traffic_across_midnight_lands_in_two_days(
    session: AsyncSession, node_id: int
) -> None:
    connected = datetime(2026, 9, 22, 23, 50, tzinfo=UTC)
    await traffic.collect(
        session, node_id, [oc(bytes_in=100, connected=connected)], connected + 5 * MIN
    )
    await traffic.collect(
        session, node_id, [oc(bytes_in=300, connected=connected)], connected + 15 * MIN
    )
    assert await daily(session) == {
        "c1-d1@2026-09-22": (100, 0),
        "c1-d1@2026-09-23": (200, 0),
    }


async def test_a_node_clock_ahead_of_ours_never_gives_a_negative_duration(
    session: AsyncSession, node_id: int
) -> None:
    """Часы контейнера ноды могут опережать часы панели: connected_at «в будущем»."""
    ahead = oc(bytes_in=100, connected=T0 + 2 * 60 * MIN)
    await traffic.collect(session, node_id, [ahead], T0)
    assert await samples(session) == [(100, 0, 0)]


@pytest.mark.parametrize("attempt", range(5))
async def test_overlapping_polls_never_count_twice(
    committed_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, attempt: int
) -> None:
    """Опрос дольше пяти минут может наложиться на следующий. Что бы ни случилось — второй
    увидел запись первого и насчитал нуль либо упал целиком на уникальности сессии, —
    трафик не задваивается."""
    async with committed_sessionmaker() as s, s.begin():
        node_id = (await registry.ensure_local_node(s, settings)).id

    async def poll() -> traffic.CollectResult:
        async with committed_sessionmaker() as s, s.begin():
            return await traffic.collect(s, node_id, [oc(bytes_in=1000, bytes_out=2000)], T0 + MIN)

    results = await asyncio.gather(poll(), poll(), return_exceptions=True)
    assert all(isinstance(r, traffic.CollectResult | IntegrityError) for r in results)
    assert any(isinstance(r, traffic.CollectResult) for r in results)
    async with committed_sessionmaker() as s:
        assert await samples(s) == [(1000, 2000, 60)]
        assert await s.scalar(select(func.count()).select_from(SessionLog)) == 1


# --- record_session_end ----------------------------------------------------


def end(bytes_in: int, bytes_out: int = 0, *, sid: str = "7", duration: int = 600) -> SessionEnd:
    return SessionEnd("c1-d1", sid, bytes_in, bytes_out, duration, "203.0.113.1")


async def test_hook_adds_the_tail_after_the_last_poll(session: AsyncSession, node_id: int) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=1500)], T0 + 5 * MIN)
    assert await traffic.record_session_end(session, node_id, end(1800), T0 + 10 * MIN)
    assert (await samples(session))[-1][:2] == (300, 0)
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert (log.bytes_in, log.final_received, log.ended_at) == (1800, True, T0 + 10 * MIN)


async def test_repeated_hook_is_ignored(session: AsyncSession, node_id: int) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=1500)], T0 + 5 * MIN)
    assert await traffic.record_session_end(session, node_id, end(1800), T0 + 10 * MIN)
    before = await samples(session)
    assert not await traffic.record_session_end(session, node_id, end(1800), T0 + 10 * MIN)
    assert await samples(session) == before


async def test_hook_after_the_poller_already_closed_the_session(
    session: AsyncSession, node_id: int
) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=1500)], T0 + 5 * MIN)
    await traffic.collect(session, node_id, [], T0 + 10 * MIN)  # опрос закрыл запись
    assert await traffic.record_session_end(session, node_id, end(1800), T0 + 10 * MIN)
    assert (await samples(session))[-1][:2] == (300, 0)
    assert await daily(session) == {"c1-d1@2026-09-22": (1800, 0)}
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert log.ended_at == T0 + 10 * MIN  # время закрытия опросом не затёрто


async def test_hook_for_a_session_nobody_polled(session: AsyncSession, node_id: int) -> None:
    """Началась и кончилась между опросами — «слепой» случай из спеки §5."""
    assert await traffic.record_session_end(session, node_id, end(400, 900), T0 + 10 * MIN)
    assert await samples(session) == [(400, 900, 600)]
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert log.started_at == T0 + 0 * MIN  # now − duration
    assert (log.final_received, log.ended_at) == (True, T0 + 10 * MIN)


async def test_hook_does_not_touch_a_session_with_another_start_time(
    session: AsyncSession, node_id: int
) -> None:
    """Тот же ID, но начало далеко от now − duration: это другая сессия (после рестарта)."""
    await traffic.collect(session, node_id, [oc(bytes_in=900)], T0 + MIN)
    late = end(50, duration=60)  # по хуку сессия началась около T0 + 4 мин
    assert await traffic.record_session_end(session, node_id, late, T0 + 5 * MIN)
    assert await session.scalar(select(func.count()).select_from(SessionLog)) == 2


# --- usage_since / purge ---------------------------------------------------


async def test_usage_since_sums_in_and_out_from_the_period_start(
    session: AsyncSession, node_id: int
) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=100, bytes_out=50)], T0 + MIN)
    await traffic.collect(session, node_id, [oc(bytes_in=300, bytes_out=150)], T0 + 6 * MIN)
    usage = await traffic.usage_since(session, ["c1-d1", "c9-d9"], T0 + 5 * MIN)
    assert usage == {"c1-d1": 300, "c9-d9": 0}  # первый сэмпл до начала периода не считается
    assert await traffic.usage_since(session, ["c1-d1"], T0) == {"c1-d1": 450}  # 150 + 300
    assert await traffic.usage_since(session, [], T0) == {}


async def test_purge_removes_only_old_samples_and_keeps_daily(
    session: AsyncSession, node_id: int
) -> None:
    await traffic.collect(session, node_id, [oc(bytes_in=100)], T0 + MIN)
    await traffic.collect(session, node_id, [oc(bytes_in=200)], T0 + 100 * 24 * 60 * MIN)
    assert await traffic.purge_samples(session, T0 + 50 * 24 * 60 * MIN) == 1
    assert len(await samples(session)) == 1
    assert len(await daily(session)) == 2  # суточные итоги хранятся бессрочно
