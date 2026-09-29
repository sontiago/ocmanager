"""Учёт трафика: дельты между опросами occtl и финальные счётчики из disconnect.sh.

Счётчики сессии в occtl кумулятивные, поэтому в БД хранится последнее учтённое
значение и считается прирост. Два источника (опрос раз в 5 минут и хук при
отключении) дополняют друг друга: сессия, начавшаяся и закончившаяся между
опросами, видна только хуку (спека §5).
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.nodes.models import SessionLog, TrafficDaily, TrafficSample
from ocmanager.nodes.occtl.parser import OcSession

# Хук знает длительность, но не время начала: сессию находим по username, ID и
# времени начала «около now − duration». Допуск на округления и задержку хука.
HOOK_MATCH_TOLERANCE = timedelta(seconds=120)


def counter_delta(prev: int, current: int) -> int:
    """Счётчики сессии монотонны; уменьшение значит, что это уже другая сессия
    с тем же ID (ocserv перезапускался) — считаем с нуля."""
    return current - prev if current >= prev else current


@dataclass(frozen=True)
class SessionEnd:
    username: str
    session_id: str
    bytes_in: int
    bytes_out: int
    duration_sec: int
    remote_ip: str | None


@dataclass(frozen=True)
class CollectResult:
    seen: int
    opened: int
    closed: int
    bytes_in: int
    bytes_out: int
    usernames: frozenset[str]  # у кого что-то изменилось: онлайн сейчас или только что отключился


async def _add_traffic(
    session: AsyncSession,
    node_id: int,
    username: str,
    now: datetime,
    *,
    bytes_in: int,
    bytes_out: int,
    duration_sec: int,
) -> None:
    """Сэмпл и суточный итог. Нулевой прирост не пишется."""
    if bytes_in == 0 and bytes_out == 0:
        return
    duration_sec = max(duration_sec, 0)
    session.add(
        TrafficSample(
            node_id=node_id,
            username=username,
            ts=now,
            bytes_in_delta=bytes_in,
            bytes_out_delta=bytes_out,
            duration_sec=duration_sec,
        )
    )
    day: date = now.astimezone(UTC).date()
    stmt = insert(TrafficDaily).values(
        username=username,
        node_id=node_id,
        day=day,
        bytes_in=bytes_in,
        bytes_out=bytes_out,
        duration_sec=duration_sec,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[TrafficDaily.username, TrafficDaily.node_id, TrafficDaily.day],
            set_={
                "bytes_in": TrafficDaily.bytes_in + stmt.excluded.bytes_in,
                "bytes_out": TrafficDaily.bytes_out + stmt.excluded.bytes_out,
                "duration_sec": TrafficDaily.duration_sec + stmt.excluded.duration_sec,
            },
        )
    )


async def collect(
    session: AsyncSession, node_id: int, sessions: Sequence[OcSession], now: datetime
) -> CollectResult:
    """Один опрос ноды. `sessions` — полный текущий список (occtl show users)."""
    open_logs = {
        (log.ocserv_session_id, log.started_at): log
        for log in await session.scalars(
            select(SessionLog)
            .where(SessionLog.node_id == node_id, SessionLog.ended_at.is_(None))
            .with_for_update()
        )
    }
    opened = total_in = total_out = 0
    touched: set[str] = set()
    alive: set[tuple[str, datetime]] = set()
    for s in sessions:
        key = (s.session_id, s.connected_at)
        alive.add(key)
        touched.add(s.username)
        log = open_logs.get(key)
        if log is None:
            # Новая сессия: всё, что она уже передала, раньше не учитывалось.
            opened += 1
            d_in, d_out = s.bytes_in, s.bytes_out
            duration = int((now - s.connected_at).total_seconds())
            session.add(
                SessionLog(
                    node_id=node_id,
                    username=s.username,
                    ocserv_session_id=s.session_id,
                    started_at=s.connected_at,
                    client_ip=s.remote_ip,
                    vpn_ip=s.vpn_ip,
                    bytes_in=s.bytes_in,
                    bytes_out=s.bytes_out,
                    last_polled_at=now,
                )
            )
        else:
            d_in = counter_delta(log.bytes_in, s.bytes_in)
            d_out = counter_delta(log.bytes_out, s.bytes_out)
            duration = int((now - log.last_polled_at).total_seconds())
            log.bytes_in, log.bytes_out, log.last_polled_at = s.bytes_in, s.bytes_out, now
            log.vpn_ip = s.vpn_ip
        total_in += d_in
        total_out += d_out
        await _add_traffic(
            session, node_id, s.username, now, bytes_in=d_in, bytes_out=d_out, duration_sec=duration
        )

    closed = 0
    for key, log in open_logs.items():
        if key not in alive:
            log.ended_at = now  # хвост доберёт disconnect-хук, если он ещё придёт
            touched.add(log.username)
            closed += 1
    await session.flush()
    return CollectResult(
        seen=len(sessions),
        opened=opened,
        closed=closed,
        bytes_in=total_in,
        bytes_out=total_out,
        usernames=frozenset(touched),
    )


async def record_session_end(
    session: AsyncSession, node_id: int, end: SessionEnd, now: datetime
) -> bool:
    """Финальные счётчики из хука. True — учтены; False — этот хук уже был (повтор)."""
    started_guess = now - timedelta(seconds=end.duration_sec)
    log = await session.scalar(
        select(SessionLog)
        .where(
            SessionLog.node_id == node_id,
            SessionLog.ocserv_session_id == end.session_id,
            SessionLog.username == end.username,
            SessionLog.started_at.between(
                started_guess - HOOK_MATCH_TOLERANCE, started_guess + HOOK_MATCH_TOLERANCE
            ),
        )
        .order_by(SessionLog.started_at.desc())
        .limit(1)
        .with_for_update()
    )
    if log is None:
        # Сессия началась и кончилась между опросами: учитываем целиком.
        session.add(
            SessionLog(
                node_id=node_id,
                username=end.username,
                ocserv_session_id=end.session_id,
                started_at=started_guess,
                ended_at=now,
                client_ip=end.remote_ip,
                bytes_in=end.bytes_in,
                bytes_out=end.bytes_out,
                last_polled_at=now,
                final_received=True,
            )
        )
        await _add_traffic(
            session,
            node_id,
            end.username,
            now,
            bytes_in=end.bytes_in,
            bytes_out=end.bytes_out,
            duration_sec=end.duration_sec,
        )
        await session.flush()
        return True
    if log.final_received:
        return False
    await _add_traffic(
        session,
        node_id,
        end.username,
        now,
        bytes_in=counter_delta(log.bytes_in, end.bytes_in),
        bytes_out=counter_delta(log.bytes_out, end.bytes_out),
        duration_sec=int((now - log.last_polled_at).total_seconds()),
    )
    log.bytes_in, log.bytes_out = end.bytes_in, end.bytes_out
    log.last_polled_at = now
    log.ended_at = log.ended_at or now
    log.final_received = True
    await session.flush()
    return True


async def usage_since(
    session: AsyncSession, usernames: Collection[str], since: datetime
) -> dict[str, int]:
    """Сумма in+out по каждому username с момента `since`. Есть в ответе все запрошенные."""
    totals = dict.fromkeys(usernames, 0)
    if not totals:
        return totals
    rows = await session.execute(
        select(
            TrafficSample.username,
            func.sum(TrafficSample.bytes_in_delta + TrafficSample.bytes_out_delta),
        )
        .where(TrafficSample.username.in_(totals), TrafficSample.ts >= since)
        .group_by(TrafficSample.username)
    )
    for username, total in rows:
        totals[username] = int(total)
    return totals


async def purge_samples(session: AsyncSession, older_than: datetime) -> int:
    """Суточные итоги остаются навсегда; сырые сэмплы старше срока хранения удаляются."""
    result = await session.execute(
        delete(TrafficSample).where(TrafficSample.ts < older_than).returning(TrafficSample.id)
    )
    return len(result.all())
