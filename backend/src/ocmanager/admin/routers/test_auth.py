from datetime import UTC, datetime, timedelta

import pyotp
import pytest
import time_machine
from arq import ArqRedis
from conftest import ADMIN_PASSWORD, MakeAdmin, NewClient
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit.models import AuditLog
from ocmanager.core import security

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


async def login(
    client: AsyncClient, username: str = "alice", password: str = ADMIN_PASSWORD, **extra: str
) -> Response:
    return await client.post(
        "/admin/auth/login", json={"username": username, "password": password, **extra}
    )


async def audit_actions(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(AuditLog.action).order_by(AuditLog.id)))


async def test_login_sets_a_hardened_cookie_and_returns_csrf(
    anon_client: AsyncClient, make_admin: MakeAdmin, session: AsyncSession
) -> None:
    admin = await make_admin("alice")
    r = await login(anon_client)
    assert r.status_code == 200
    body = r.json()
    assert body["admin"]["username"] == "alice"
    assert len(body["csrf_token"]) >= 43
    assert "password" not in r.text
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("ocm_admin=")
    for flag in ("HttpOnly", "SameSite=strict", "Path=/admin"):
        assert flag in cookie
    token = anon_client.cookies["ocm_admin"]
    stored = await session.scalar(select(AdminSession))
    assert stored is not None
    assert stored.token_hash == security.sha256_hex(token)
    assert stored.token_hash != token
    await session.refresh(admin)
    assert admin.last_login_at is not None
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "admin.login"))
    assert row is not None
    assert row.actor_id == str(admin.id)
    assert row.ip is not None


async def test_wrong_password_and_unknown_login_look_the_same(
    anon_client: AsyncClient, make_admin: MakeAdmin, session: AsyncSession
) -> None:
    await make_admin("alice")
    wrong = await login(anon_client, password="not-the-password")
    ghost = await login(anon_client, username="ghost")
    assert wrong.status_code == ghost.status_code == 401
    assert wrong.json() == ghost.json()
    assert wrong.json()["error"]["code"] == "unauthorized"
    assert "ocm_admin" not in anon_client.cookies
    # Запись о неудаче пережила исключение: она закоммичена до ответа 401.
    assert await audit_actions(session) == [
        "admin.create",
        "admin.login_failed",
        "admin.login_failed",
    ]


async def test_unknown_login_costs_a_password_check(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, fast_bcrypt: None
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(security, "dummy_verify", lambda: calls.append(1))
    await login(anon_client, username="ghost")
    assert calls == [1]


async def test_a_password_typed_into_the_login_field_never_reaches_the_audit_log(
    anon_client: AsyncClient, session: AsyncSession, fast_bcrypt: None
) -> None:
    await login(anon_client, username="Hunter2 hunter2 hunter2")
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "admin.login_failed"))
    assert row is not None
    assert row.details == {"username": None, "reason": "unknown_user"}


async def test_five_attempts_pass_and_the_sixth_is_429(
    anon_client: AsyncClient, make_admin: MakeAdmin
) -> None:
    await make_admin("alice")
    for _ in range(5):
        assert (await login(anon_client, password="nope")).status_code == 401
    r = await login(anon_client)  # пароль верный, но окно исчерпано
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) > 0
    other = await login(anon_client, username="bob")  # другой логин — свой счётчик
    assert other.status_code == 401


async def test_a_good_login_resets_the_counter(
    anon_client: AsyncClient, make_admin: MakeAdmin
) -> None:
    await make_admin("alice")
    for _ in range(4):
        await login(anon_client, password="nope")
    assert (await login(anon_client)).status_code == 200
    for _ in range(4):
        assert (await login(anon_client, password="nope")).status_code == 401


async def test_malformed_login_bodies_are_422(anon_client: AsyncClient) -> None:
    for body in (
        {"username": "a", "password": "x" * 1025},
        {"username": "a" * 65, "password": "x"},
        {"username": "a", "password": "x", "extra": 1},
        {"username": "a"},
    ):
        assert (await anon_client.post("/admin/auth/login", json=body)).status_code == 422


async def test_no_cookie_or_a_forged_cookie_is_401(anon_client: AsyncClient) -> None:
    assert (await anon_client.get("/admin/auth/me")).status_code == 401
    anon_client.cookies.set("ocm_admin", "forged", domain="localhost.local", path="/admin")
    assert (await anon_client.get("/admin/auth/me")).status_code == 401


async def test_me_returns_the_csrf_token_again(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/admin/auth/me")
    assert r.status_code == 200
    assert r.json()["csrf_token"] == admin_client.headers["X-CSRF-Token"]


async def test_unsafe_methods_need_the_csrf_token(admin_client: AsyncClient) -> None:
    good = admin_client.headers.pop("X-CSRF-Token")
    r = await admin_client.post("/admin/auth/logout")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "csrf_failed")
    r = await admin_client.post("/admin/auth/logout", headers={"X-CSRF-Token": "someone-elses"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "csrf_failed")
    assert (await admin_client.get("/admin/auth/me")).status_code == 200  # чтение без токена
    r = await admin_client.post("/admin/auth/logout", headers={"X-CSRF-Token": good})
    assert r.status_code == 204


async def test_logout_kills_the_session_on_the_server(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    stolen = admin_client.cookies["ocm_admin"]
    assert (await admin_client.post("/admin/auth/logout")).status_code == 204
    assert await session.scalar(select(AdminSession)) is None
    admin_client.cookies.clear()
    admin_client.cookies.set("ocm_admin", stolen, domain="localhost.local", path="/admin")
    assert (await admin_client.get("/admin/auth/me")).status_code == 401
    assert "admin.logout" in await audit_actions(session)


async def test_session_expires_after_twelve_hours_of_silence(
    anon_client: AsyncClient, make_admin: MakeAdmin, session: AsyncSession
) -> None:
    await make_admin("alice")
    with time_machine.travel(NOW, tick=False):
        await login(anon_client)
    with time_machine.travel(NOW + timedelta(hours=11), tick=False):
        assert (await anon_client.get("/admin/auth/me")).status_code == 200
    with time_machine.travel(NOW + timedelta(hours=11 + 12, minutes=1), tick=False):
        assert (await anon_client.get("/admin/auth/me")).status_code == 401
    assert await session.scalar(select(AdminSession)) is None


async def test_session_dies_after_seven_days_even_if_used(
    anon_client: AsyncClient, make_admin: MakeAdmin
) -> None:
    await make_admin("alice")
    with time_machine.travel(NOW, tick=False):
        await login(anon_client)
    for step in range(1, 15):  # заход каждые 11 часов: простоя нет
        with time_machine.travel(NOW + timedelta(hours=11 * step), tick=False):
            assert (await anon_client.get("/admin/auth/me")).status_code == 200
    with time_machine.travel(NOW + timedelta(hours=11 * 16), tick=False):  # 176 ч > 168 ч
        assert (await anon_client.get("/admin/auth/me")).status_code == 401


async def test_last_seen_is_touched_at_most_once_a_minute(
    anon_client: AsyncClient, make_admin: MakeAdmin, session: AsyncSession
) -> None:
    await make_admin("alice")
    with time_machine.travel(NOW, tick=False):
        await login(anon_client)
    with time_machine.travel(NOW + timedelta(seconds=30), tick=False):
        await anon_client.get("/admin/auth/me")
    stored = await session.scalar(select(AdminSession))
    assert stored is not None
    assert stored.last_seen_at == NOW
    with time_machine.travel(NOW + timedelta(seconds=90), tick=False):
        await anon_client.get("/admin/auth/me")
    await session.refresh(stored)
    assert stored.last_seen_at == NOW + timedelta(seconds=90)


async def test_deactivated_admin_is_locked_out_at_once(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    admin = await session.scalar(select(Admin))
    assert admin is not None
    admin.is_active = False
    await session.flush()
    assert (await admin_client.get("/admin/auth/me")).status_code == 401
    assert (await login(admin_client)).status_code == 401


async def test_password_change_closes_every_other_session(
    admin_client: AsyncClient, new_client: NewClient, session: AsyncSession
) -> None:
    async with new_client() as other:
        assert (await login(other)).status_code == 200
        r = await admin_client.post(
            "/admin/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": "a-brand-new-password"},
        )
        assert r.status_code == 204
        assert (await other.get("/admin/auth/me")).status_code == 401
    assert (await admin_client.get("/admin/auth/me")).status_code == 200  # эта сессия жива
    async with new_client() as fresh:
        assert (await login(fresh)).status_code == 401  # старый пароль больше не работает
        assert (await login(fresh, password="a-brand-new-password")).status_code == 200
    assert "admin.password_change" in await audit_actions(session)


async def test_password_change_refuses_a_wrong_current_or_a_weak_new_password(
    admin_client: AsyncClient,
) -> None:
    wrong = await admin_client.post(
        "/admin/auth/password", json={"current_password": "nope", "new_password": "x" * 20}
    )
    assert wrong.status_code == 403
    weak = await admin_client.post(
        "/admin/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": "short"}
    )
    assert weak.status_code == 422


async def test_password_guessing_from_a_stolen_session_is_rate_limited(
    admin_client: AsyncClient,
) -> None:
    body = {"current_password": "nope", "new_password": "x" * 20}
    for _ in range(5):
        assert (await admin_client.post("/admin/auth/password", json=body)).status_code == 403
    assert (await admin_client.post("/admin/auth/password", json=body)).status_code == 429


async def enable_totp(client: AsyncClient) -> str:
    secret = (await client.post("/admin/auth/totp/setup")).json()["secret"]
    code = pyotp.TOTP(secret).now()
    assert (await client.post("/admin/auth/totp/confirm", json={"code": code})).status_code == 204
    return str(secret)


async def test_totp_setup_confirm_and_login(
    admin_client: AsyncClient,
    new_client: NewClient,
    session: AsyncSession,
    redis: ArqRedis,
) -> None:
    r = await admin_client.post("/admin/auth/totp/setup")
    uri, secret = r.json()["otpauth_uri"], r.json()["secret"]
    assert uri.startswith("otpauth://totp/") and secret in uri  # noqa: PT018
    stored = await session.scalar(select(Admin.totp_secret))
    assert stored is not None and secret not in stored  # noqa: PT018 — в БД секрет зашифрован

    wrong = await admin_client.post("/admin/auth/totp/confirm", json={"code": "000000"})
    assert wrong.status_code == 422
    ok = await admin_client.post(
        "/admin/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert ok.status_code == 204
    assert (await admin_client.post("/admin/auth/totp/setup")).status_code == 409

    async with new_client() as other:
        need = await login(other)
        assert (need.status_code, need.json()["error"]["code"]) == (401, "totp_required")
        bad = await login(other, totp_code="000000")
        assert (bad.status_code, bad.json()["error"]["code"]) == (401, "unauthorized")
        good = await login(other, totp_code=pyotp.TOTP(secret).now())
        assert good.status_code == 200
    assert "admin.totp_enable" in await audit_actions(session)


async def test_totp_confirm_without_setup_is_409(admin_client: AsyncClient) -> None:
    r = await admin_client.post("/admin/auth/totp/confirm", json={"code": "123456"})
    assert r.status_code == 409


async def test_totp_disable_needs_a_valid_code(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    secret = await enable_totp(admin_client)
    assert (
        await admin_client.post("/admin/auth/totp/disable", json={"code": "000000"})
    ).status_code == 422
    r = await admin_client.post("/admin/auth/totp/disable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204
    admin = await session.scalar(select(Admin))
    assert admin is not None
    await session.refresh(admin)
    assert (admin.totp_enabled, admin.totp_secret) == (False, None)
    assert (
        await admin_client.post("/admin/auth/totp/disable", json={"code": "1"})
    ).status_code == 409


async def test_sessions_list_and_delete(admin_client: AsyncClient, new_client: NewClient) -> None:
    async with new_client() as other:
        await login(other)
        rows = (await admin_client.get("/admin/auth/sessions")).json()
        assert len(rows) == 2
        assert sum(r["current"] for r in rows) == 1
        theirs = next(r["id"] for r in rows if not r["current"])
        assert (await admin_client.delete(f"/admin/auth/sessions/{theirs}")).status_code == 204
        assert (await other.get("/admin/auth/me")).status_code == 401
    assert (await admin_client.delete(f"/admin/auth/sessions/{theirs}")).status_code == 404


async def test_a_foreign_session_cannot_be_deleted(
    admin_client: AsyncClient, new_client: NewClient, make_admin: MakeAdmin
) -> None:
    await make_admin("bob")
    async with new_client() as bob:
        await login(bob, username="bob")
        bobs = (await bob.get("/admin/auth/sessions")).json()[0]["id"]
    r = await admin_client.delete(f"/admin/auth/sessions/{bobs}")
    assert r.status_code == 404
