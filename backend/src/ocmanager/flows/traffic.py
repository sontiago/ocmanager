"""Склейка nodes (сессии, трафик) + provisioning (устройства) + subscriptions (лимиты):
опрос нод и перенос израсходованного трафика в подписки."""

from collections.abc import Collection
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.core.config import Settings
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.nodes import registry, traffic
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.occtl.parser import OcctlParseError
from ocmanager.nodes.traffic import CollectResult
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client, Subscription

log = structlog.get_logger(__name__)


async def apply_usage(session: AsyncSession, usernames: Collection[str], now: datetime) -> None:
    """Для затронутых username: last_seen_at устройств и израсходованный трафик подписок.

    Трафик клиента — сумма по всем его устройствам (и отозванным: трафик был) с начала
    расчётного периода. Считается по сырым сэмплам, а не по суточным итогам: период
    начинается не с полуночи, а сэмплы живут дольше периода."""
    if not usernames:
        return
    await session.execute(
        update(Device).where(Device.ocserv_username.in_(usernames)).values(last_seen_at=now)
    )
    client_ids = set(
        await session.scalars(select(Device.client_id).where(Device.ocserv_username.in_(usernames)))
    )
    for client_id in sorted(client_ids):
        # Порядок блокировок один на все операции (subscriptions.service._lock): клиент, затем
        # подписка. Иначе проверка квоты ниже замкнулась бы в кольцо с продлением или блокировкой.
        await session.scalar(select(Client.id).where(Client.id == client_id).with_for_update())
        # FOR UPDATE: параллельное продление сбрасывает счётчик, и наш устаревший
        # результат не должен его затереть.
        sub = await session.scalar(
            select(Subscription).where(Subscription.client_id == client_id).with_for_update()
        )
        if sub is None:
            continue
        names = list(
            await session.scalars(
                select(Device.ocserv_username).where(Device.client_id == client_id)
            )
        )
        used = sum((await traffic.usage_since(session, names, sub.traffic_period_start)).values())
        before = sub.traffic_used_bytes
        if used != before:
            sub.traffic_used_bytes = used
        # Квота выбрана — доступ закрывается здесь же, а не ждёт следующего cron.
        await subscription_flows.enforce_quota(session, client_id, now)
        await subscriptions.warn_quota(session, client_id, before_used=before)


async def collect_traffic(
    session: AsyncSession, settings: Settings, now: datetime
) -> dict[int, CollectResult]:
    """Опрос всех активных нод. Недоступная нода пропускается целиком: без списка сессий
    нельзя отличить «сессия кончилась» от «нода молчит», поэтому открытые записи не трогаем."""
    await registry.ensure_local_node(session, settings)
    results: dict[int, CollectResult] = {}
    touched: set[str] = set()
    for node in await registry.get_active_nodes(session):
        driver = registry.driver_for(node, settings)
        try:
            sessions = await driver.list_sessions()
        except (NodeUnreachable, OcctlParseError) as exc:
            log.warning("traffic_collect_skipped", node_id=node.id, error=str(exc))
            continue
        result = await traffic.collect(session, node.id, sessions, now)
        results[node.id] = result
        touched |= result.usernames
    await apply_usage(session, touched, now)
    return results


async def purge_samples(session: AsyncSession, now: datetime) -> int:
    retention = (await settings_store.load(session)).traffic_retention_days
    return await traffic.purge_samples(session, now - timedelta(days=retention))
