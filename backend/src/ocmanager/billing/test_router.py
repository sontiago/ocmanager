from typing import Any

import pytest
from arq import ArqRedis
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from ocmanager.billing.models import WebhookEvent
from ocmanager.billing.testing import sign, webhook_body
from ocmanager.billing.webhooks import MAX_BODY_BYTES
from ocmanager.core.config import Settings
from ocmanager.events.models import EventOutbox

URL = "/webhooks/tribute"
SIGNATURE = "trbt-signature"


@pytest.fixture
def api_key(settings: Settings) -> str:
    assert settings.tribute_api_key is not None
    return settings.tribute_api_key.get_secret_value()


def signed(body: bytes, key: str) -> dict[str, str]:
    return {SIGNATURE: sign(body, key)}


async def rows(session: AsyncSession) -> list[WebhookEvent]:
    return list(await session.scalars(select(WebhookEvent).order_by(WebhookEvent.id)))


async def webhook_jobs(redis: ArqRedis) -> list[tuple[Any, ...]]:
    """Очередь, отфильтрованная до обработки вебхуков (kick_dispatch кладёт туда свои job-ы)."""
    return [j.args for j in await redis.queued_jobs() if j.function == "process_webhook"]


async def test_a_signed_webhook_is_stored_byte_for_byte_and_queued(
    public_client: AsyncClient, session: AsyncSession, redis: ArqRedis, api_key: str
) -> None:
    # Пробелы, перевод строки, кириллица: подпись считается по этим байтам, а не по JSON.
    body = (
        '{"name":  "new_subscription" ,\n "payload":{"telegram_user_id":7001,"note":"Привет"}}'
    ).encode()
    r = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}

    [row] = await rows(session)
    assert (row.provider, row.signature_ok, row.status, row.attempts) == (
        "tribute",
        True,
        "received",
        0,
    )
    assert bytes(row.raw_body) == body
    assert row.payload["name"] == "new_subscription"
    assert await webhook_jobs(redis) == [(row.id,)]


async def test_the_same_webhook_body_is_stored_once(
    public_client: AsyncClient, session: AsyncSession, redis: ArqRedis, api_key: str
) -> None:
    body = webhook_body("new_subscription")
    first = await public_client.post(URL, content=body, headers=signed(body, api_key))
    second = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert (first.status_code, first.json()) == (200, {"status": "ok"})
    assert (second.status_code, second.json()) == (200, {"status": "duplicate"})
    assert len(await rows(session)) == 1
    assert len(await webhook_jobs(redis)) == 1


async def test_different_bodies_are_different_events(
    public_client: AsyncClient, session: AsyncSession, api_key: str
) -> None:
    for name in ("new_subscription", "renewed_subscription"):
        body = webhook_body(name)
        assert (
            await public_client.post(URL, content=body, headers=signed(body, api_key))
        ).status_code == 200
    assert len(await rows(session)) == 2


async def test_a_bad_signature_is_a_401_and_leaves_a_rejected_row(
    public_client: AsyncClient, session: AsyncSession, redis: ArqRedis
) -> None:
    body = webhook_body("new_subscription")
    r = await public_client.post(URL, content=body, headers={SIGNATURE: "0" * 64})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")

    [row] = await rows(session)
    assert (row.signature_ok, row.status, row.payload) == (False, "rejected", {})
    assert bytes(row.raw_body) == body  # следователю нужно видеть, что пришло
    assert await webhook_jobs(redis) == []
    assert list(await session.scalars(select(EventOutbox.name))) == ["webhook.rejected"]


async def test_a_missing_signature_is_a_401(public_client: AsyncClient) -> None:
    r = await public_client.post(URL, content=webhook_body("new_subscription"))
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")


async def test_a_signature_made_with_another_key_is_a_401(public_client: AsyncClient) -> None:
    body = webhook_body("new_subscription")
    r = await public_client.post(URL, content=body, headers=signed(body, "some-other-key"))
    assert r.status_code == 401


async def test_a_non_ascii_signature_is_a_clean_401_not_a_crash(
    public_client: AsyncClient,
) -> None:
    r = await public_client.post(
        URL, content=webhook_body("new_subscription"), headers={SIGNATURE.encode(): "ключ".encode()}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")


async def test_a_rejected_webhook_does_not_occupy_the_id_of_the_real_one(
    public_client: AsyncClient, session: AsyncSession, api_key: str
) -> None:
    body = webhook_body("new_subscription")
    await public_client.post(URL, content=body, headers={SIGNATURE: "0" * 64})
    r = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert (r.status_code, r.json()) == (200, {"status": "ok"})
    assert sorted(row.status for row in await rows(session)) == ["received", "rejected"]


async def test_bad_signatures_are_rate_limited(
    public_client: AsyncClient, session: AsyncSession, api_key: str
) -> None:
    body = webhook_body("new_subscription")
    for _ in range(30):
        r = await public_client.post(URL, content=body, headers={SIGNATURE: "0" * 64})
        assert r.status_code == 401
    r = await public_client.post(URL, content=body, headers={SIGNATURE: "0" * 64})
    assert (r.status_code, r.json()["error"]["code"]) == (429, "rate_limited")
    assert len(await rows(session)) == 30  # 31-й в таблицу не попал

    # Настоящий провайдер флудом не заблокирован.
    ok = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert ok.status_code == 200


async def test_an_unknown_provider_is_a_404(public_client: AsyncClient) -> None:
    r = await public_client.post("/webhooks/nope", content=b"{}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


async def test_without_an_api_key_the_provider_does_not_exist(
    public_app: FastAPI, public_client: AsyncClient, settings: Settings
) -> None:
    public_app.state.settings = settings.model_copy(update={"tribute_api_key": None})
    body = webhook_body("new_subscription")
    r = await public_client.post(URL, content=body, headers={SIGNATURE: "0" * 64})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


async def test_an_oversized_body_is_refused_and_not_stored(
    public_client: AsyncClient, session: AsyncSession, api_key: str
) -> None:
    body = b"x" * (MAX_BODY_BYTES + 1)
    r = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")
    assert await rows(session) == []


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[" * 100_000,  # глубже лимита рекурсии json
        b'{"name":"x\\u0000y"}',  # JSONB не хранит \u0000
        b"[1,2,3]",  # JSON, но не объект
    ],
    ids=["not-json", "too-deep", "nul-escape", "not-an-object"],
)
async def test_bodies_postgres_cannot_store_as_jsonb_do_not_crash_the_intake(
    public_client: AsyncClient, session: AsyncSession, api_key: str, body: bytes
) -> None:
    r = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert r.status_code == 200, r.text
    [row] = await rows(session)
    assert (row.status, row.payload) == ("received", {})
    assert bytes(row.raw_body) == body


async def test_no_secret_reaches_the_logs(public_client: AsyncClient, api_key: str) -> None:
    body = webhook_body("new_subscription")
    bad = "a" * 64
    with capture_logs() as logs:
        await public_client.post(URL, content=body, headers={SIGNATURE: bad})
        await public_client.post(URL, content=body, headers=signed(body, api_key))
    dump = repr(logs)
    assert api_key not in dump
    assert bad not in dump
    assert sign(body, api_key) not in dump
    assert any(entry["event"] == "webhook_rejected" for entry in logs)


async def test_the_intake_survives_a_dead_queue(
    public_client: AsyncClient,
    public_app: FastAPI,
    session: AsyncSession,
    api_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis лёг после записи: провайдер всё равно получает 200, а событие остаётся `received`
    и его подхватит cron-подметальщик (Задача 5.5)."""

    async def broken(*_: Any, **__: Any) -> None:
        raise ConnectionError("redis is gone")

    monkeypatch.setattr(public_app.state.redis, "enqueue_job", broken)
    body = webhook_body("new_subscription")
    r = await public_client.post(URL, content=body, headers=signed(body, api_key))
    assert r.status_code == 200
    [row] = await rows(session)
    assert row.status == "received"
