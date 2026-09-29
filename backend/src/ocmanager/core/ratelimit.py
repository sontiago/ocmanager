"""Ограничитель частоты на Redis: окно фиксированной длины, счётчик на ключ."""

from redis.asyncio import Redis

from ocmanager.core.errors import RateLimited


def _key(key: str) -> str:
    return f"rl:{key}"


async def hit(redis: Redis, key: str, *, limit: int, window_s: int) -> None:
    """Считает обращение. Первые `limit` проходят, следующие — `RateLimited` до конца окна.

    INCR и EXPIRE идут одной транзакцией: если бы процесс умер между ними, ключ остался бы
    без срока жизни и заблокировал бы обращения навсегда. `NX` ставит срок только новому
    окну — повторные обращения его не продлевают."""
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(_key(key))
        pipe.expire(_key(key), window_s, nx=True)
        pipe.ttl(_key(key))
        count, _, ttl = await pipe.execute()
    if count > limit:
        raise RateLimited(retry_after=max(int(ttl), 1))


async def reset(redis: Redis, key: str) -> None:
    await redis.delete(_key(key))
