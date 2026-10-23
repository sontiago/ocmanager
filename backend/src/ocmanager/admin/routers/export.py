"""Выгрузка в CSV. Фильтры и порядок строк те же, что у списков: обработчики вызывают сами
`list_*` постранично, поэтому логика отбора живёт в одном месте."""

import csv
import io
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ocmanager.admin.deps import AdminContext, CurrentAdmin
from ocmanager.admin.pagination import Page, PageParams
from ocmanager.admin.routers import audit as audit_router
from ocmanager.admin.routers import clients as clients_router
from ocmanager.admin.routers import payments as payments_router
from ocmanager.admin.routers import stats as stats_router
from ocmanager.admin.routers import subscriptions as subscriptions_router
from ocmanager.audit import service as audit
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.subscriptions.state import MAX_DAYS

router = APIRouter(prefix="/export", tags=["export"])

PAGE_SIZE = 200
MAX_ROWS = 100_000

COLUMNS: dict[str, list[str]] = {
    "clients": [
        "id",
        "telegram_id",
        "username",
        "first_name",
        "lang",
        "is_blocked",
        "trial_used_at",
        "created_at",
        "subscription_status",
        "plan_code",
        "expires_at",
        "devices_active",
    ],
    "subscriptions": [
        "client_id",
        "telegram_id",
        "username",
        "first_name",
        "status",
        "plan_code",
        "plan_is_trial",
        "started_at",
        "expires_at",
        "auto_renew",
        "traffic_used_bytes",
        "traffic_limit_bytes",
    ],
    "payments": [
        "id",
        "client_id",
        "subscription_id",
        "provider",
        "external_id",
        "plan_id",
        "amount",
        "currency",
        "status",
        "received_at",
        "processed_at",
    ],
    "audit": [
        "id",
        "created_at",
        "actor_type",
        "actor_id",
        "ip",
        "action",
        "target_type",
        "target_id",
        "details",
    ],
    "traffic": ["day", "bytes_in", "bytes_out"],
}

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    """Строка для ячейки. Текст, начинающийся с `=`, `+`, `-`, `@`, Excel исполнит как формулу
    (имя клиента приходит из Telegram), поэтому такой текст получает ведущий апостроф."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _major(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


def _row(kind: str, item: BaseModel) -> dict[str, Any]:
    data = item.model_dump(mode="json")
    if kind == "payments":
        data["amount"] = _major(data["amount"])
    return data


async def _collect(
    fetch: Callable[[PageParams], Awaitable[Page[Any]]],
) -> tuple[list[Any], bool]:
    """Все строки списка постранично, но не больше MAX_ROWS; второе значение — были ли обрезаны."""
    items: list[Any] = []
    offset = 0
    while True:
        page = await fetch(PageParams(limit=PAGE_SIZE, offset=offset))
        room = MAX_ROWS - len(items)
        items.extend(page.items[:room])
        offset += len(page.items)
        if len(items) >= MAX_ROWS:
            return items, offset < page.total or len(page.items) > room
        if not page.items or offset >= page.total:
            return items, False


async def _respond(
    db: AsyncSession,
    ctx: AdminContext,
    kind: str,
    items: list[Any],
    truncated: bool,
    filters: dict[str, Any],
) -> Response:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    columns = COLUMNS[kind]
    writer.writerow(columns)
    for item in items:
        data = item if isinstance(item, dict) else _row(kind, item)
        writer.writerow([_cell(data.get(c)) for c in columns])

    # Кто и что выгрузил — в журнал: выгрузка уносит персональные данные клиентов.
    await audit.record(
        db,
        ctx.actor,
        f"export.{kind}",
        target_type="export",
        details={"filters": jsonable_encoder(filters), "rows": len(items)},
    )
    await db.commit()

    filename = f"ocmanager-{kind}-{utcnow().date().isoformat()}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    # BOM: без него Excel читает UTF-8 как cp1251 и ломает кириллицу.
    return Response(
        content=("﻿" + out.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def _given(**params: Any) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


@router.get("/clients.csv")
async def export_clients(
    ctx: CurrentAdmin,
    db: SessionDep,
    q: Annotated[str | None, Query(max_length=64)] = None,
    status: clients_router.ClientStatus | None = None,
    blocked: bool | None = None,
) -> Response:
    items, truncated = await _collect(
        lambda p: clients_router.list_clients(ctx, db, p, q=q, status=status, blocked=blocked)
    )
    return await _respond(
        db, ctx, "clients", items, truncated, _given(q=q, status=status, blocked=blocked)
    )


@router.get("/subscriptions.csv")
async def export_subscriptions(
    ctx: CurrentAdmin,
    db: SessionDep,
    status: subscriptions_router.SubStatus | None = None,
    plan: Annotated[str | None, Query(max_length=64)] = None,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=MAX_DAYS)] = None,
) -> Response:
    items, truncated = await _collect(
        lambda p: subscriptions_router.list_subscriptions(
            ctx, db, p, status=status, plan=plan, expiring_within_days=expiring_within_days
        )
    )
    filters = _given(status=status, plan=plan, expiring_within_days=expiring_within_days)
    return await _respond(db, ctx, "subscriptions", items, truncated, filters)


@router.get("/payments.csv")
async def export_payments(
    ctx: CurrentAdmin,
    db: SessionDep,
    client_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
    status: payments_router.PaymentStatus | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> Response:
    items, truncated = await _collect(
        lambda p: payments_router.list_payments(
            ctx, db, p, client_id=client_id, status=status, since=since, until=until
        )
    )
    filters = _given(client_id=client_id, status=status, since=since, until=until)
    return await _respond(db, ctx, "payments", items, truncated, filters)


@router.get("/audit.csv")
async def export_audit(
    ctx: CurrentAdmin,
    db: SessionDep,
    actor_type: Literal["admin", "system", "client"] | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> Response:
    items, truncated = await _collect(
        lambda p: audit_router.list_audit(
            ctx,
            db,
            p,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            since=since,
            until=until,
        )
    )
    filters = _given(
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
    )
    return await _respond(db, ctx, "audit", items, truncated, filters)


@router.get("/traffic.csv")
async def export_traffic(
    ctx: CurrentAdmin,
    db: SessionDep,
    days: Annotated[int, Query(ge=1, le=stats_router.MAX_DAYS)] = 30,
) -> Response:
    stats = await stats_router.traffic(ctx, db, days)
    return await _respond(db, ctx, "traffic", list(stats.days), False, {"days": days})
