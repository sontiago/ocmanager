from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Date, cast, func, select
from sqlalchemy.orm import InstrumentedAttribute

from ocmanager.admin.deps import CurrentAdmin
from ocmanager.billing.models import Payment, Plan
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.nodes.models import TrafficDaily
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.state import LIVE

router = APIRouter(prefix="/stats", tags=["stats"])

MAX_DAYS = 366
TOP_CLIENTS = 10
DaysParam = Annotated[int, Query(ge=1, le=MAX_DAYS)]


def _window(days: int) -> tuple[list[date], datetime]:
    """Последние `days` суток UTC, включая сегодняшние: список дней и момент начала окна."""
    today = utcnow().date()
    labels = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    return labels, datetime.combine(labels[0], datetime.min.time(), tzinfo=UTC)


def _utc_day(column: InstrumentedAttribute[datetime]) -> ColumnElement[date]:
    return cast(func.timezone("UTC", column), Date)


class TrafficPoint(BaseModel):
    day: date
    bytes_in: int
    bytes_out: int


class TopClient(BaseModel):
    client_id: int
    name: str
    username: str | None
    bytes_in: int
    bytes_out: int


class TrafficStats(BaseModel):
    days: list[TrafficPoint]  # каждый день окна, без пропусков
    top_clients: list[TopClient]  # по сумме байт; трафик устройств, которых нет в БД, не входит


@router.get("/traffic")
async def traffic(ctx: CurrentAdmin, db: SessionDep, days: DaysParam = 30) -> TrafficStats:
    labels, _ = _window(days)
    first = labels[0]
    totals = {
        day: (int(rx), int(tx))
        for day, rx, tx in await db.execute(
            select(
                TrafficDaily.day,
                func.coalesce(func.sum(TrafficDaily.bytes_in), 0),
                func.coalesce(func.sum(TrafficDaily.bytes_out), 0),
            )
            .where(TrafficDaily.day >= first)
            .group_by(TrafficDaily.day)
        )
    }
    rx_sum = func.sum(TrafficDaily.bytes_in)
    tx_sum = func.sum(TrafficDaily.bytes_out)
    top = await db.execute(
        select(Client.id, Client.first_name, Client.username, rx_sum, tx_sum)
        .select_from(TrafficDaily)
        .join(Device, Device.ocserv_username == TrafficDaily.username)
        .join(Client, Client.id == Device.client_id)
        .where(TrafficDaily.day >= first)
        .group_by(Client.id, Client.first_name, Client.username)
        .order_by((rx_sum + tx_sum).desc(), Client.id)
        .limit(TOP_CLIENTS)
    )
    return TrafficStats(
        days=[
            TrafficPoint(
                day=d, bytes_in=totals.get(d, (0, 0))[0], bytes_out=totals.get(d, (0, 0))[1]
            )
            for d in labels
        ],
        top_clients=[
            TopClient(client_id=cid, name=name, username=uname, bytes_in=int(rx), bytes_out=int(tx))
            for cid, name, uname, rx, tx in top
        ],
    )


class RevenuePoint(BaseModel):
    day: date
    amounts: dict[str, int]  # валюта → минорные единицы; пусто — платежей в этот день не было


class CurrencyTotal(BaseModel):
    currency: str
    amount: int
    count: int
    refunded_amount: int
    refunded_count: int


class RevenueStats(BaseModel):
    series: list[RevenuePoint]
    totals: list[CurrencyTotal]


@router.get("/revenue")
async def revenue(ctx: CurrentAdmin, db: SessionDep, days: DaysParam = 30) -> RevenueStats:
    labels, start = _window(days)
    day = _utc_day(Payment.received_at)
    per_day: dict[date, dict[str, int]] = defaultdict(dict)
    for d, currency, amount in await db.execute(
        select(day, Payment.currency, func.sum(Payment.amount))
        .where(Payment.status == "succeeded", Payment.received_at >= start)
        .group_by(day, Payment.currency)
    ):
        per_day[d][currency] = int(amount)

    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"amount": 0, "count": 0, "refunded_amount": 0, "refunded_count": 0}
    )
    for currency, status, amount, count in await db.execute(
        select(Payment.currency, Payment.status, func.sum(Payment.amount), func.count())
        .where(Payment.received_at >= start)
        .group_by(Payment.currency, Payment.status)
    ):
        prefix = "" if status == "succeeded" else "refunded_"
        totals[currency][f"{prefix}amount"] = int(amount)
        totals[currency][f"{prefix}count"] = int(count)
    return RevenueStats(
        series=[RevenuePoint(day=d, amounts=per_day.get(d, {})) for d in labels],
        totals=[CurrencyTotal(currency=c, **v) for c, v in sorted(totals.items())],
    )


class ClientsPoint(BaseModel):
    day: date
    count: int


class ClientsStats(BaseModel):
    series: list[ClientsPoint]  # новые клиенты по дням
    total: int
    new_in_period: int
    paying_in_period: int  # клиенты хотя бы с одним успешным платежом за период


@router.get("/clients")
async def clients(ctx: CurrentAdmin, db: SessionDep, days: DaysParam = 30) -> ClientsStats:
    labels, start = _window(days)
    day = _utc_day(Client.created_at)
    new = {
        d: int(n)
        for d, n in await db.execute(
            select(day, func.count()).where(Client.created_at >= start).group_by(day)
        )
    }
    total = await db.scalar(select(func.count()).select_from(Client))
    paying = await db.scalar(
        select(func.count(func.distinct(Payment.client_id))).where(
            Payment.status == "succeeded", Payment.received_at >= start
        )
    )
    return ClientsStats(
        series=[ClientsPoint(day=d, count=new.get(d, 0)) for d in labels],
        total=int(total or 0),
        new_in_period=sum(new.values()),
        paying_in_period=int(paying or 0),
    )


class EconomicsStats(BaseModel):
    mrr: dict[str, int]  # валюта → ежемесячная выручка, минорные единицы
    arpu: dict[str, int]
    active_paid: int


@router.get("/economics")
async def economics(ctx: CurrentAdmin, db: SessionDep) -> EconomicsStats:
    """MRR — оценка по живым платным подпискам: цена тарифа за 30 суток. Цена берётся из тарифа
    сейчас, а не на момент покупки: снимка цены в подписке нет."""
    rows = await db.execute(
        select(Plan.currency, Plan.price_amount, Plan.duration_days)
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.status.in_([s.value for s in LIVE]), ~Subscription.plan_is_trial)
    )
    mrr: dict[str, Decimal] = defaultdict(Decimal)
    count: dict[str, int] = defaultdict(int)
    for currency, price, duration in rows:
        mrr[currency] += Decimal(price) * 30 / Decimal(duration)
        count[currency] += 1
    return EconomicsStats(
        mrr={c: round(v) for c, v in sorted(mrr.items())},
        arpu={c: round(mrr[c] / count[c]) for c in sorted(mrr)},
        active_paid=sum(count.values()),
    )
