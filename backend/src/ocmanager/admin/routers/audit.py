from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import ColumnElement, func, select

from ocmanager.admin.deps import CurrentAdmin
from ocmanager.admin.pagination import Page, PageDep, page_of
from ocmanager.admin.schemas import AuditRow
from ocmanager.audit.models import AuditLog
from ocmanager.core.db import SessionDep

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def list_audit(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    actor_type: Literal["admin", "system", "client"] | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> Page[AuditRow]:
    """Журнал, новые первыми. Фильтры складываются по «и». Время — только с часовым
    поясом (`2026-09-29T00:00:00Z`): наивное сравнилось бы с timestamptz ошибкой БД."""
    conds: list[ColumnElement[bool]] = []
    if actor_type is not None:
        conds.append(AuditLog.actor_type == actor_type)
    if action is not None:
        conds.append(AuditLog.action == action)
    if target_type is not None:
        conds.append(AuditLog.target_type == target_type)
    if target_id is not None:
        conds.append(AuditLog.target_id == target_id)
    if since is not None:
        conds.append(AuditLog.created_at >= since)
    if until is not None:
        conds.append(AuditLog.created_at < until)

    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*conds))
    rows = await db.scalars(
        select(AuditLog)
        .where(*conds)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return page_of([AuditRow.of(a) for a in rows], int(total or 0), page)
