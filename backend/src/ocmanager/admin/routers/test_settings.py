from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakeClient
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.core.config import Settings
from ocmanager.flows import trial


@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_a_session_is_required(anon_client: AsyncClient, method: str) -> None:
    assert (await anon_client.request(method, "/admin/settings")).status_code == 401


async def test_patch_needs_the_csrf_token(admin_client: AsyncClient) -> None:
    del admin_client.headers["X-CSRF-Token"]
    assert (await admin_client.patch("/admin/settings", json={})).status_code == 403


async def test_defaults_and_the_environment_summary(
    admin_client: AsyncClient, settings: Settings
) -> None:
    body = (await admin_client.get("/admin/settings")).json()
    assert body["runtime"]["trial_days"] == 3
    assert body["runtime"]["default_lang"] == "ru"
    env = body["environment"]
    assert env["env"] == "test"
    assert env["vpn_host"] == settings.vpn_host
    assert set(env) == {"env", "vpn_host", "ocserv_container", "version"}


async def test_no_secret_of_the_process_reaches_the_response(
    admin_client: AsyncClient, settings: Settings
) -> None:
    secrets = [
        v.get_secret_value()
        for v in (getattr(settings, name) for name in type(settings).model_fields)
        if isinstance(v, SecretStr)
    ]
    assert len(secrets) >= 2  # secret_key и internal_token
    sensitive = [*secrets, settings.database_url, settings.redis_url, "ocm:ocm"]
    for response in (
        await admin_client.get("/admin/settings"),
        await admin_client.patch("/admin/settings", json={"trial_days": 4}),
    ):
        for value in sensitive:
            assert value not in response.text


async def test_patch_updates_validates_and_audits(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    r = await admin_client.patch(
        "/admin/settings",
        json={"trial_days": 7, "default_lang": "en", "support_url": "https://t.me/support"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["runtime"]["trial_days"] == 7
    assert (await admin_client.get("/admin/settings")).json()["runtime"]["default_lang"] == "en"
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "settings.update"))
    assert row is not None
    assert row.actor_type == "admin"
    assert row.details["changed"]["trial_days"] == [3, 7]


async def test_a_patch_that_changes_nothing_is_not_audited(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    for body in ({}, {"trial_days": 3}):
        assert (await admin_client.patch("/admin/settings", json=body)).status_code == 200
    rows = await session.scalars(select(AuditLog).where(AuditLog.action == "settings.update"))
    assert list(rows) == []


@pytest.mark.parametrize(
    "body",
    [
        {"trial_days": 0},
        {"trial_days": 31},
        {"trial_days": "many"},
        {"trial_traffic_bytes": -1},
        {"default_lang": "de"},
        {"support_url": "javascript:alert(1)"},
        {"traffic_retention_days": 6},
        {"admin_chat_ids": "42"},
        {"no_such_setting": 1},
    ],
)
async def test_bad_values_and_unknown_keys_are_422(
    admin_client: AsyncClient, session: AsyncSession, body: dict[str, Any]
) -> None:
    r = await admin_client.patch("/admin/settings", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")
    assert (await admin_client.get("/admin/settings")).json()["runtime"]["trial_days"] == 3


async def test_a_bad_field_rejects_the_whole_patch(admin_client: AsyncClient) -> None:
    r = await admin_client.patch("/admin/settings", json={"trial_days": 9, "default_lang": "de"})
    assert r.status_code == 422
    assert (await admin_client.get("/admin/settings")).json()["runtime"]["trial_days"] == 3


async def test_a_json_list_is_not_a_patch(admin_client: AsyncClient) -> None:
    assert (await admin_client.patch("/admin/settings", json=[1])).status_code == 422


async def test_the_next_trial_uses_the_new_length(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    trial_plan: Plan,
) -> None:
    await admin_client.patch("/admin/settings", json={"trial_days": 7})
    now = datetime(2026, 9, 29, 12, tzinfo=UTC)
    sub = await trial.start_trial(
        session, client_id=(await make_client()).id, actor=Actor.system(), now=now
    )
    assert sub.expires_at == now + timedelta(days=7)
