import asyncio
import base64
from datetime import UTC, datetime, timedelta

import pytest
from arq import ArqRedis
from cryptography.fernet import Fernet

from ocmanager.core.crypto import derive_fernet
from ocmanager.provisioning import delivery

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
P12 = b"\x30\x82PKCS12-BYTES\x00\xff" * 20


@pytest.fixture
def fernet() -> Fernet:
    return derive_fernet("k" * 32, purpose=b"p12-delivery")


async def test_take_returns_the_file_once(redis: ArqRedis, fernet: Fernet) -> None:
    ticket = await delivery.put_p12(redis, fernet, P12, filename="c1-d1.p12", now=NOW)
    assert ticket.expires_at == NOW + timedelta(seconds=900)
    assert await delivery.take_p12(redis, fernet, ticket.token) == ("c1-d1.p12", P12)
    assert await delivery.take_p12(redis, fernet, ticket.token) is None


async def test_unknown_token(redis: ArqRedis, fernet: Fernet) -> None:
    assert await delivery.take_p12(redis, fernet, "no-such-token") is None


async def test_tokens_are_distinct(redis: ArqRedis, fernet: Fernet) -> None:
    a = await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    b = await delivery.put_p12(redis, fernet, P12, filename="b.p12", now=NOW)
    assert a.token != b.token
    assert (await delivery.take_p12(redis, fernet, b.token)) == ("b.p12", P12)


async def test_link_lives_at_most_15_minutes(redis: ArqRedis, fernet: Fernet) -> None:
    await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    [key] = await redis.keys("p12:*")
    assert 0 < await redis.ttl(key) <= delivery.LINK_TTL_S == 900


async def test_expired_link_is_gone(redis: ArqRedis, fernet: Fernet) -> None:
    ticket = await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    [key] = await redis.keys("p12:*")
    await redis.pexpire(key, 1)
    await asyncio.sleep(0.05)
    assert await delivery.take_p12(redis, fernet, ticket.token) is None


async def test_redis_holds_neither_the_file_nor_the_token(redis: ArqRedis, fernet: Fernet) -> None:
    ticket = await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    [key] = await redis.keys("p12:*")
    stored = await redis.get(key)
    assert P12 not in stored
    assert base64.b64encode(P12) not in stored
    assert ticket.token.encode() not in key
    assert ticket.token.encode() not in stored


async def test_tampered_or_foreign_value_is_treated_as_missing(
    redis: ArqRedis, fernet: Fernet
) -> None:
    ticket = await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    [key] = await redis.keys("p12:*")
    await redis.set(key, b"garbage")
    assert await delivery.take_p12(redis, fernet, ticket.token) is None

    ticket = await delivery.put_p12(redis, fernet, P12, filename="a.p12", now=NOW)
    other = derive_fernet("z" * 32, purpose=b"p12-delivery")
    assert await delivery.take_p12(redis, other, ticket.token) is None
