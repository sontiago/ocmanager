import pytest
from arq import ArqRedis

from ocmanager.core import ratelimit
from ocmanager.core.errors import RateLimited


async def test_first_five_pass_and_the_sixth_is_refused(redis: ArqRedis) -> None:
    for _ in range(5):
        await ratelimit.hit(redis, "k", limit=5, window_s=60)
    with pytest.raises(RateLimited) as caught:
        await ratelimit.hit(redis, "k", limit=5, window_s=60)
    assert 0 < caught.value.retry_after <= 60
    assert caught.value.headers() == {"Retry-After": str(caught.value.retry_after)}


async def test_keys_are_independent(redis: ArqRedis) -> None:
    for _ in range(5):
        await ratelimit.hit(redis, "a", limit=5, window_s=60)
    await ratelimit.hit(redis, "b", limit=5, window_s=60)


async def test_reset_starts_over(redis: ArqRedis) -> None:
    for _ in range(5):
        await ratelimit.hit(redis, "k", limit=5, window_s=60)
    await ratelimit.reset(redis, "k")
    await ratelimit.hit(redis, "k", limit=5, window_s=60)


async def test_later_hits_do_not_extend_the_window(redis: ArqRedis) -> None:
    await ratelimit.hit(redis, "k", limit=5, window_s=60)
    await redis.expire("rl:k", 30)  # окно «прожито» наполовину
    await ratelimit.hit(redis, "k", limit=5, window_s=60)
    assert await redis.ttl("rl:k") <= 30


async def test_the_key_always_has_an_expiry(redis: ArqRedis) -> None:
    await ratelimit.hit(redis, "k", limit=5, window_s=60)
    assert await redis.ttl("rl:k") > 0
