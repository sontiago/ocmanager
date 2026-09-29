from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from ocmanager.admin import accounts, auth
from ocmanager.admin.deps import CurrentAdmin, RedisDep, SettingsDep, client_ip
from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit import service as audit
from ocmanager.core import ratelimit, security
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import Conflict, Forbidden, InvalidInput, NotFound

router = APIRouter(prefix="/auth", tags=["auth"])

# Смена пароля и подтверждение TOTP требуют «знания секрета» от уже вошедшего: с украденной
# cookie их можно перебирать, поэтому и здесь есть предел.
SECRET_LIMIT = 5
SECRET_WINDOW_S = 15 * 60


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)
    totp_code: str | None = Field(None, max_length=16)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class CodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=16)


class AdminOut(BaseModel):
    id: int
    username: str
    role: str
    totp_enabled: bool
    last_login_at: datetime | None

    @classmethod
    def of(cls, admin: Admin) -> "AdminOut":
        return cls(
            id=admin.id,
            username=admin.username,
            role=admin.role,
            totp_enabled=admin.totp_enabled,
            last_login_at=admin.last_login_at,
        )


class AuthOut(BaseModel):
    admin: AdminOut
    csrf_token: str


class TotpSetupOut(BaseModel):
    otpauth_uri: str
    secret: str


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


@router.post("/login")
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> AuthOut:
    result = await auth.login(
        db,
        redis,
        settings,
        username=body.username,
        password=body.password,
        totp_code=body.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        now=utcnow(),
    )
    response.set_cookie(
        auth.COOKIE,
        result.token,
        max_age=int(auth.MAX_LIFETIME.total_seconds()),
        httponly=True,
        samesite="strict",
        path="/admin",
    )
    return AuthOut(admin=AdminOut.of(result.admin), csrf_token=result.session.csrf_token)


@router.post("/logout", status_code=204)
async def logout(ctx: CurrentAdmin, db: SessionDep) -> Response:
    await db.execute(delete(AdminSession).where(AdminSession.id == ctx.session.id))
    await audit.record(
        db, ctx.actor, "admin.logout", target_type="admin", target_id=str(ctx.admin.id)
    )
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(auth.COOKIE, path="/admin")
    return response


@router.get("/me")
async def me(ctx: CurrentAdmin) -> AuthOut:
    """SPA после перезагрузки страницы забирает отсюда CSRF-токен."""
    return AuthOut(admin=AdminOut.of(ctx.admin), csrf_token=ctx.session.csrf_token)


async def _guard(redis: RedisDep, name: str, admin: Admin) -> None:
    await ratelimit.hit(
        redis, f"admin_{name}:{admin.id}", limit=SECRET_LIMIT, window_s=SECRET_WINDOW_S
    )


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> Response:
    await _guard(redis, "password", ctx.admin)
    if not security.verify_password(body.current_password, ctx.admin.password_hash):
        raise Forbidden("wrong current password")
    await accounts.set_password(
        db, ctx.admin, body.new_password, ctx.actor, keep_session_id=ctx.session.id
    )
    await db.commit()
    return Response(status_code=204)


def _secret_of(admin: Admin, settings: SettingsDep) -> str:
    assert admin.totp_secret is not None
    return auth.totp_fernet(settings).decrypt(admin.totp_secret.encode()).decode()


@router.post("/totp/setup")
async def totp_setup(ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep) -> TotpSetupOut:
    """Готовит секрет; включается он только после `confirm` с рабочим кодом."""
    if ctx.admin.totp_enabled:
        raise Conflict("totp is already enabled")
    secret = security.new_totp_secret()
    ctx.admin.totp_secret = auth.totp_fernet(settings).encrypt(secret.encode()).decode()
    await db.commit()
    return TotpSetupOut(otpauth_uri=security.totp_uri(secret, ctx.admin.username), secret=secret)


@router.post("/totp/confirm", status_code=204)
async def totp_confirm(
    body: CodeBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    await _guard(redis, "totp", ctx.admin)
    if ctx.admin.totp_enabled:
        raise Conflict("totp is already enabled")
    if ctx.admin.totp_secret is None:
        raise Conflict("call /totp/setup first")
    if not security.verify_totp(_secret_of(ctx.admin, settings), body.code, now=utcnow()):
        raise InvalidInput("wrong code")
    ctx.admin.totp_enabled = True
    await audit.record(
        db, ctx.actor, "admin.totp_enable", target_type="admin", target_id=str(ctx.admin.id)
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/totp/disable", status_code=204)
async def totp_disable(
    body: CodeBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    await _guard(redis, "totp", ctx.admin)
    if not ctx.admin.totp_enabled:
        raise Conflict("totp is not enabled")
    if not security.verify_totp(_secret_of(ctx.admin, settings), body.code, now=utcnow()):
        raise InvalidInput("wrong code")
    ctx.admin.totp_enabled = False
    ctx.admin.totp_secret = None
    await audit.record(
        db, ctx.actor, "admin.totp_disable", target_type="admin", target_id=str(ctx.admin.id)
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/sessions")
async def list_sessions(ctx: CurrentAdmin, db: SessionDep) -> list[SessionOut]:
    rows = await db.scalars(
        select(AdminSession)
        .where(AdminSession.admin_id == ctx.admin.id)
        .order_by(AdminSession.last_seen_at.desc())
    )
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            ip=None if s.ip is None else str(s.ip),
            user_agent=s.user_agent,
            current=s.id == ctx.session.id,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int, ctx: CurrentAdmin, db: SessionDep) -> Response:
    result = await db.execute(
        delete(AdminSession)
        .where(AdminSession.id == session_id, AdminSession.admin_id == ctx.admin.id)
        .returning(AdminSession.id)
    )
    if not result.all():
        raise NotFound("session not found")
    await db.commit()
    return Response(status_code=204)
