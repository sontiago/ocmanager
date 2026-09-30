from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.deps import CaDep, CurrentAdmin, RedisDep, SettingsDep, commit_and_kick
from ocmanager.admin.schemas import DriftOut, HealthOut, NodeOut
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import NodeUnavailable
from ocmanager.flows.nodes import check_node_health, run_node_action
from ocmanager.flows.reconcile import Drift, reconcile_node
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.logs import sse_lines
from ocmanager.nodes.models import Node
from ocmanager.nodes.occtl.parser import OcctlParseError
from ocmanager.nodes.service import NodeAction
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Client

log = structlog.get_logger(__name__)
router = APIRouter(tags=["node"])


class NodeStatusOut(BaseModel):
    node: NodeOut
    health: HealthOut | None  # из кэша воркера; None — кэш пуст
    last_reconcile_report: dict[str, Any] | None


class LiveSessionOut(BaseModel):
    session_id: str
    username: str
    remote_ip: str
    vpn_ip: str | None
    bytes_in: int
    bytes_out: int
    connected_at: datetime
    user_agent: str | None
    # Кто это. Всё None — ocserv видит username, которого нет в БД (чужая сессия).
    device_id: int | None
    device_name: str | None
    client_id: int | None
    telegram_id: int | None
    client_name: str | None


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: NodeAction
    username: str | None = Field(None, max_length=64)


class ReconcileOut(BaseModel):
    node_id: int
    started_at: datetime
    finished_at: datetime
    drifts: list[DriftOut]
    error: str | None


async def local_node(db: AsyncSession, settings: SettingsDep) -> tuple[Node, NodeDriver]:
    """Единственная нода этапа 1. Строка создаётся при первом обращении и сразу коммитится."""
    node = await registry.ensure_local_node(db, settings)
    await db.commit()
    return node, registry.driver_for(node, settings)


def _drift(d: Drift) -> DriftOut:
    return DriftOut(kind=d.kind, details=d.details)


@router.get("/node")
async def node_status(
    ctx: CurrentAdmin, db: SessionDep, redis: RedisDep, settings: SettingsDep
) -> NodeStatusOut:
    node, _ = await local_node(db, settings)
    cached = await service.cached_health(redis, node.id)
    return NodeStatusOut(
        node=NodeOut.of(node),
        health=None if cached is None else HealthOut.of(cached),
        last_reconcile_report=node.last_reconcile_report,
    )


@router.post("/node/probe")
async def probe(
    ctx: CurrentAdmin, db: SessionDep, redis: RedisDep, settings: SettingsDep
) -> HealthOut:
    """Живая проверка, а не кэш: обновляет и кэш, и статус ноды."""
    node, driver = await local_node(db, settings)
    health = await check_node_health(db, node, driver, redis)
    await commit_and_kick(db, redis)
    return HealthOut.of(health)


@router.get("/node/sessions")
async def live_sessions(
    ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep
) -> list[LiveSessionOut]:
    """Текущие сессии прямо с ноды (`occtl`), с именами клиента и устройства."""
    _, driver = await local_node(db, settings)
    try:
        sessions = await driver.list_sessions()
    except NodeUnreachable as exc:
        raise NodeUnavailable(str(exc)) from exc
    except OcctlParseError as exc:
        raise NodeUnavailable(f"unexpected occtl output: {exc}") from exc
    owners = {
        d.ocserv_username: (d, c)
        for d, c in await db.execute(
            select(Device, Client)
            .join(Client, Client.id == Device.client_id)
            .where(Device.ocserv_username.in_({s.username for s in sessions}))
        )
    }
    out: list[LiveSessionOut] = []
    for s in sessions:
        owner = owners.get(s.username)
        device, client = owner if owner else (None, None)
        out.append(
            LiveSessionOut(
                session_id=s.session_id,
                username=s.username,
                remote_ip=s.remote_ip,
                vpn_ip=s.vpn_ip,
                bytes_in=s.bytes_in,
                bytes_out=s.bytes_out,
                connected_at=s.connected_at,
                user_agent=s.user_agent,
                device_id=None if device is None else device.id,
                device_name=None if device is None else device.name,
                client_id=None if client is None else client.id,
                telegram_id=None if client is None else client.telegram_id,
                client_name=None if client is None else client.first_name,
            )
        )
    return out


@router.post("/node/actions", status_code=204)
async def node_action(
    body: ActionBody, ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep
) -> None:
    """Только действия из реестра `NodeAction`: произвольная команда на ноде невозможна
    по построению. Аудит пишется лишь для выполненного действия."""
    node, driver = await local_node(db, settings)
    await run_node_action(db, node, driver, body.action, ctx.actor, username=body.username)
    await db.commit()


@router.post("/node/reconcile")
async def reconcile(
    ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep, ca: CaDep
) -> ReconcileOut:
    """Сверка прямо сейчас. Найденное чинится, отчёт сохраняется в строке ноды.
    Сбой ноды — не ошибка запроса, а поле `error` отчёта."""
    node, driver = await local_node(db, settings)
    report = await reconcile_node(db, node, driver, ca, utcnow())
    await db.commit()
    return ReconcileOut(
        node_id=node.id,
        started_at=report.started_at,
        finished_at=report.finished_at,
        drifts=[_drift(d) for d in report.drifts],
        error=report.error,
    )


@router.get("/node/logs")
async def node_logs(
    ctx: CurrentAdmin,
    db: SessionDep,
    settings: SettingsDep,
    tail: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> StreamingResponse:
    """Живые логи ocserv потоком SSE. Пока клиент подключён, идёт `docker logs -f`; при обрыве
    соединения процесс завершается (shell.stream закрывается вместе с генератором)."""
    driver = registry.local_driver(settings)
    if (await driver.probe()).container_state == "missing":
        raise NodeUnavailable("container missing")
    # Поток живёт часами: соединение с БД на это время не держим.
    await db.close()

    async def body() -> AsyncIterator[bytes]:
        try:
            async with driver.stream_logs(tail=tail) as lines:
                async for chunk in sse_lines(lines):
                    yield chunk
        except NodeUnreachable as exc:
            log.warning("node_logs_failed", error=str(exc))
            yield b"event: error\ndata: node unavailable\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
