from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import ColumnElement, func, select

from ocmanager.admin.deps import CurrentAdmin, RedisDep
from ocmanager.admin.pagination import BigId, Page, PageDep, page_of
from ocmanager.admin.schemas import PaymentOut
from ocmanager.billing.models import Payment, WebhookEvent
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import NotFound
from ocmanager.flows import purchase as purchase_flows

log = structlog.get_logger(__name__)

router = APIRouter(tags=["payments"])

PaymentStatus = Literal["succeeded", "refunded"]
WebhookFilter = Literal["received", "processed", "ignored", "failed", "dead", "rejected", "all"]
NEEDS_ATTENTION = ("failed", "dead")


class WebhookOut(BaseModel):
    id: int
    provider: str
    external_event_id: str
    signature_ok: bool
    status: str
    attempts: int
    last_error: str | None
    received_at: datetime
    processed_at: datetime | None

    @classmethod
    def of(cls, w: WebhookEvent) -> "WebhookOut":
        return cls(
            id=w.id,
            provider=w.provider,
            external_event_id=w.external_event_id,
            signature_ok=w.signature_ok,
            status=w.status,
            attempts=w.attempts,
            last_error=w.last_error,
            received_at=w.received_at,
            processed_at=w.processed_at,
        )


class WebhookDetail(WebhookOut):
    payload: dict[str, Any]  # разобранное тело; сырые байты наружу не отдаём


@router.get("/payments")
async def list_payments(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    client_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
    status: PaymentStatus | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> Page[PaymentOut]:
    conds: list[ColumnElement[bool]] = []
    if client_id is not None:
        conds.append(Payment.client_id == client_id)
    if status is not None:
        conds.append(Payment.status == status)
    if since is not None:
        conds.append(Payment.received_at >= since)
    if until is not None:
        conds.append(Payment.received_at < until)
    total = await db.scalar(select(func.count()).select_from(Payment).where(*conds))
    rows = await db.scalars(
        select(Payment)
        .where(*conds)
        .order_by(Payment.received_at.desc(), Payment.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return page_of([PaymentOut.of(p) for p in rows], int(total or 0), page)


@router.get("/webhooks")
async def list_webhooks(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    status: WebhookFilter | None = None,
    provider: Annotated[str | None, Query(max_length=32)] = None,
) -> Page[WebhookOut]:
    """Без `status` — только те, что ждут человека: `failed` и `dead`."""
    conds: list[ColumnElement[bool]] = []
    if status is None:
        conds.append(WebhookEvent.status.in_(NEEDS_ATTENTION))
    elif status != "all":
        conds.append(WebhookEvent.status == status)
    if provider is not None:
        conds.append(WebhookEvent.provider == provider)
    total = await db.scalar(select(func.count()).select_from(WebhookEvent).where(*conds))
    rows = await db.scalars(
        select(WebhookEvent)
        .where(*conds)
        .order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return page_of([WebhookOut.of(w) for w in rows], int(total or 0), page)


@router.get("/webhooks/{webhook_id}")
async def webhook_detail(webhook_id: BigId, ctx: CurrentAdmin, db: SessionDep) -> WebhookDetail:
    row = await db.get(WebhookEvent, webhook_id)
    if row is None:
        raise NotFound("webhook not found")
    return WebhookDetail(**WebhookOut.of(row).model_dump(), payload=row.payload)


@router.post("/webhooks/{webhook_id}/reprocess")
async def reprocess_webhook(
    webhook_id: BigId, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> WebhookOut:
    """`failed`/`dead` → `received` и в очередь. Платёж, записанный при первой попытке, не
    дублируется: обработка идемпотентна (П5-13)."""
    row = await purchase_flows.requeue_webhook(db, webhook_id, ctx.actor)
    out = WebhookOut.of(row)
    await db.commit()
    try:
        await redis.enqueue_job("process_webhook", webhook_id)
    except Exception as exc:
        # Статус уже received: cron-подметальщик подхватит его в течение пары минут.
        log.warning("webhook_enqueue_failed", webhook_event_id=webhook_id, exc_info=exc)
    return out
