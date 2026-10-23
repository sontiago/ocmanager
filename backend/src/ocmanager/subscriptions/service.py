"""Клиенты и подписки. Аудит здесь не пишется: subscriptions не импортирует
домен audit (граница модулей) — его пишут функции из flows/."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Boolean, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.errors import (
    InvalidTransition,
    NotApplicable,
    NotFound,
    SubscriptionInactive,
    TrialAlreadyUsed,
)
from ocmanager.events import bus
from ocmanager.events.types import (
    ClientBlocked,
    ClientUnblocked,
    DomainEvent,
    SubscriptionActivated,
    SubscriptionAutoRenewCancelled,
    SubscriptionExpired,
    SubscriptionRenewed,
    TrafficExhausted,
    TrafficReset,
)
from ocmanager.subscriptions import state as state_mod
from ocmanager.subscriptions.models import Client, ReferralReward, Subscription
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.state import LIVE, PlanTerms, Status, SubState, has_access


def lang_from_telegram(code: str | None) -> Literal["ru", "en"]:
    """ru, ru-RU → ru; всё остальное, включая отсутствие, → en (решение C4 плана TMA)."""
    return "ru" if code is not None and code.lower().startswith("ru") else "en"


@dataclass(frozen=True)
class UpsertResult:
    client: Client
    created: bool


async def upsert_client(session: AsyncSession, ident: TelegramIdentity) -> UpsertResult:
    """Создаёт клиента или обновляет имя, username и язык из Telegram.
    Один SQL-запрос: два одновременных первых захода не дадут дубля."""
    values = {
        "telegram_id": ident.telegram_id,
        "first_name": ident.first_name,
        "username": ident.username,
        "lang": lang_from_telegram(ident.language_code),
    }
    stmt = insert(Client).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Client.telegram_id],
        set_={k: stmt.excluded[k] for k in ("first_name", "username", "lang")}
        | {"updated_at": text("now()")},
    )
    # xmax = 0 только у строки, вставленной этим запросом.
    inserted = literal_column("(xmax = 0)", Boolean).label("inserted")
    row = (
        await session.execute(
            stmt.returning(Client, inserted).execution_options(populate_existing=True)
        )
    ).one()
    return UpsertResult(client=row[0], created=bool(row[1]))


async def get_client(session: AsyncSession, client_id: int) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFound("client not found")
    return client


async def find_client_by_telegram_id(session: AsyncSession, telegram_id: int) -> Client | None:
    client: Client | None = await session.scalar(
        select(Client).where(Client.telegram_id == telegram_id)
    )
    return client


# --- подписки ----------------------------------------------------------------

EXPIRY_BATCH = 500


def to_state(sub: Subscription) -> SubState:
    return SubState(
        status=Status(sub.status),
        plan_id=sub.plan_id,
        plan_is_trial=sub.plan_is_trial,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        auto_renew=sub.auto_renew,
        device_limit=sub.device_limit,
        traffic_limit_bytes=sub.traffic_limit_bytes,
        traffic_period_start=sub.traffic_period_start,
        traffic_used_bytes=sub.traffic_used_bytes,
    )


def _write(sub: Subscription, state: SubState) -> None:
    sub.status = state.status.value
    sub.plan_id = state.plan_id
    sub.plan_is_trial = state.plan_is_trial
    sub.started_at = state.started_at
    sub.expires_at = state.expires_at
    sub.auto_renew = state.auto_renew
    sub.device_limit = state.device_limit
    sub.traffic_limit_bytes = state.traffic_limit_bytes
    sub.traffic_used_bytes = state.traffic_used_bytes
    sub.traffic_period_start = state.traffic_period_start


async def get_subscription(session: AsyncSession, client_id: int) -> Subscription | None:
    sub: Subscription | None = await session.scalar(
        select(Subscription).where(Subscription.client_id == client_id)
    )
    return sub


async def _lock(session: AsyncSession, client_id: int) -> tuple[Client, Subscription | None]:
    """Блокировка клиента, затем его подписки. Порядок один на все операции, поэтому
    два одновременных продления выстраиваются в очередь, а не теряют дни."""
    client: Client | None = await session.scalar(
        select(Client).where(Client.id == client_id).with_for_update()
    )
    if client is None:
        raise NotFound("client not found")
    sub: Subscription | None = await session.scalar(
        select(Subscription).where(Subscription.client_id == client_id).with_for_update()
    )
    return client, sub


def _require_not_blocked(client: Client) -> None:
    if client.is_blocked:
        raise SubscriptionInactive("client is blocked", blocked=True)


async def _save(
    session: AsyncSession, client_id: int, sub: Subscription | None, state: SubState
) -> Subscription:
    if sub is None:
        sub = Subscription(client_id=client_id)
        _write(sub, state)
        session.add(sub)
    else:
        _write(sub, state)
    await session.flush()
    return sub


def _was_live(sub: Subscription | None) -> bool:
    return sub is not None and Status(sub.status) in LIVE


async def _announce_grant(session: AsyncSession, client_id: int, *, was_live: bool) -> None:
    """Появился доступ — Activated; продлён существующий — Renewed."""
    event: DomainEvent = (
        SubscriptionRenewed(client_id=client_id)
        if was_live
        else SubscriptionActivated(client_id=client_id)
    )
    await bus.record(session, event)


async def start_trial(
    session: AsyncSession, client_id: int, terms: PlanTerms, now: datetime
) -> Subscription:
    client, sub = await _lock(session, client_id)
    _require_not_blocked(client)
    if client.trial_used_at is not None:
        raise TrialAlreadyUsed("trial already used")
    state = state_mod.start_trial(None if sub is None else to_state(sub), terms, now)
    client.trial_used_at = now
    saved = await _save(session, client_id, sub, state)
    await _announce_grant(session, client_id, was_live=False)
    return saved


async def activate(
    session: AsyncSession,
    client_id: int,
    terms: PlanTerms,
    now: datetime,
    *,
    auto_renew: bool,
    provider: str | None = None,
    external_subscription_id: str | None = None,
) -> Subscription:
    client, sub = await _lock(session, client_id)
    _require_not_blocked(client)
    state = state_mod.activate(
        None if sub is None else to_state(sub), terms, now, auto_renew=auto_renew
    )
    was_live = _was_live(sub)
    saved = await _save(session, client_id, sub, state)
    if provider is not None:
        saved.provider = provider
        saved.external_subscription_id = external_subscription_id
    await _announce_grant(session, client_id, was_live=was_live)
    return saved


async def renew(
    session: AsyncSession,
    client_id: int,
    terms: PlanTerms,
    now: datetime,
    *,
    provider: str | None = None,
    external_subscription_id: str | None = None,
) -> Subscription:
    client, sub = await _lock(session, client_id)
    _require_not_blocked(client)
    state = state_mod.renew(None if sub is None else to_state(sub), terms, now)
    was_live = _was_live(sub)
    saved = await _save(session, client_id, sub, state)
    if provider is not None:
        saved.provider = provider
        saved.external_subscription_id = external_subscription_id
    await _announce_grant(session, client_id, was_live=was_live)
    return saved


async def extend_days(
    session: AsyncSession, client_id: int, days: int, now: datetime
) -> Subscription:
    client, sub = await _lock(session, client_id)
    _require_not_blocked(client)
    if sub is None:
        raise InvalidTransition("cannot extend: no subscription")
    was_live = _was_live(sub)
    saved = await _save(session, client_id, sub, state_mod.extend(to_state(sub), days, now))
    await _announce_grant(session, client_id, was_live=was_live)
    return saved


async def cancel_auto_renew(session: AsyncSession, client_id: int) -> bool:
    """True — статус сменился. Идемпотентно: нет подписки или она не active — False, без события."""
    _, sub = await _lock(session, client_id)
    if sub is None:
        return False
    before = to_state(sub)
    after = state_mod.cancel_auto_renew(before)
    if after == before:
        return False
    await _save(session, client_id, sub, after)
    await bus.record(session, SubscriptionAutoRenewCancelled(client_id=client_id))
    return True


async def expire_due(session: AsyncSession, now: datetime) -> list[int]:
    """Переводит просроченные живые подписки в expired. Возвращает client_id.
    SKIP LOCKED: два воркера не берут одну подписку, а идущее в этот момент
    продление не теряется (оно держит блокировку)."""
    live = [s.value for s in LIVE] + [Status.EXHAUSTED.value]
    expired: list[int] = []
    while True:
        batch = list(
            await session.scalars(
                select(Subscription)
                .where(Subscription.status.in_(live), Subscription.expires_at <= now)
                .order_by(Subscription.id)
                .limit(EXPIRY_BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        for sub in batch:
            _write(sub, state_mod.expire(to_state(sub), now))
            await bus.record(session, SubscriptionExpired(client_id=sub.client_id))
            expired.append(sub.client_id)
        await session.flush()
        if len(batch) < EXPIRY_BATCH:
            return expired


async def expire_now(session: AsyncSession, client_id: int, now: datetime) -> bool:
    """Немедленно закрывает живую подписку. False — закрывать нечего (нет подписки,
    уже истекла, заблокирована): повторное нажатие безопасно и не плодит события."""
    _, sub = await _lock(session, client_id)
    if sub is None or not _was_live(sub):
        return False
    _write(sub, state_mod.expire_now(to_state(sub), now))
    await session.flush()
    await bus.record(session, SubscriptionExpired(client_id=client_id))
    return True


async def set_blocked(session: AsyncSession, client_id: int, blocked: bool, now: datetime) -> bool:
    """Блокировка клиента вместе с его подпиской. Возвращает True, если что-то изменилось."""
    client, sub = await _lock(session, client_id)
    if client.is_blocked == blocked:
        return False
    client.is_blocked = blocked
    if sub is not None:
        state = to_state(sub)
        if blocked:
            _write(sub, state_mod.block(state))
        elif state.status is Status.BLOCKED:
            _write(sub, state_mod.unblock(state, now))
    await session.flush()
    await bus.record(
        session,
        (ClientBlocked(client_id=client_id) if blocked else ClientUnblocked(client_id=client_id)),
    )
    return True


async def client_has_access(session: AsyncSession, client_id: int, now: datetime) -> bool:
    client = await get_client(session, client_id)
    sub = await get_subscription(session, client_id)
    return has_access(
        None if sub is None else to_state(sub),
        client_blocked=client.is_blocked,
        now=now,
    )


async def extend_to(session: AsyncSession, client_id: int, until: datetime, now: datetime) -> bool:
    """Продлевает живую подписку до `until`, если это позже нынешнего конца: оплаченный
    провайдером период — нижняя граница доступа. Никогда не сокращает. False — менять нечего
    (нет подписки, конец уже не раньше, срок вне разумных пределов или подписка не живая)."""
    _, sub = await _lock(session, client_id)
    if sub is None or not _was_live(sub):
        return False
    if until <= sub.expires_at or until > now + timedelta(days=state_mod.MAX_DAYS):
        return False
    sub.expires_at = until
    await session.flush()
    return True


async def enforce_quota(session: AsyncSession, client_id: int, now: datetime) -> bool:
    """Закрывает доступ, если трафик периода выбран. False — квота не исчерпана, лимита нет,
    подписка не живая (заблокированной и истёкшей квота не интересна) или уже exhausted."""
    _, sub = await _lock(session, client_id)
    if sub is None or not _was_live(sub):
        return False
    current = to_state(sub)
    limit = current.traffic_limit_bytes
    if limit is None or current.traffic_used_bytes < limit:
        return False
    _write(sub, state_mod.exhaust(current))
    await bus.record(session, TrafficExhausted(client_id=client_id))
    return True


async def reset_traffic(session: AsyncSession, client_id: int, now: datetime) -> bool:
    """Новый период трафика по решению админа. Исчерпанная подписка оживает (событие
    TrafficReset вернёт доступ на ноде). False — сбрасывать нечего: подписки нет, она истекла,
    заблокирована или счётчик и так нулевой."""
    _, sub = await _lock(session, client_id)
    if sub is None:
        return False
    status = Status(sub.status)
    if status not in LIVE and status is not Status.EXHAUSTED:
        return False
    if status is not Status.EXHAUSTED and sub.traffic_used_bytes == 0:
        return False
    fresh = state_mod.reset_traffic(to_state(sub), now)
    _write(sub, fresh)
    if status is Status.EXHAUSTED and fresh.status in LIVE:
        await bus.record(session, TrafficReset(client_id=client_id))
    return True


def _revived_from_exhausted(before: Status, after: SubState) -> bool:
    return before is Status.EXHAUSTED and after.status in LIVE


async def grant_traffic(
    session: AsyncSession, client_id: int, extra_bytes: int, now: datetime
) -> bool:
    """Бонусный трафик к лимиту текущего периода (промокод). Нужна живая или исчерпанная
    подписка с лимитом; исчерпанная оживает, если трафика теперь хватает, и доступ возвращается."""
    _, sub = await _lock(session, client_id)
    if sub is None or (
        Status(sub.status) not in LIVE and Status(sub.status) is not Status.EXHAUSTED
    ):
        raise SubscriptionInactive("no active subscription")
    if sub.traffic_limit_bytes is None:
        raise NotApplicable("the plan has no traffic limit")
    before = Status(sub.status)
    after = state_mod.grant_traffic(to_state(sub), extra_bytes, now)
    _write(sub, after)
    if _revived_from_exhausted(before, after):
        await bus.record(session, TrafficReset(client_id=client_id))
    return True


async def add_perks(
    session: AsyncSession, client_id: int, *, devices: int, traffic_bytes: int, now: datetime
) -> None:
    """Постоянные бонусы уровня: запоминаются на клиенте (их подмешают в условия при каждой
    выдаче и продлении) и сразу поднимают лимиты текущей подписки."""
    client, sub = await _lock(session, client_id)
    client.bonus_devices += devices
    client.bonus_traffic_bytes += traffic_bytes
    if sub is None:
        return
    if devices:
        sub.device_limit += devices
    status = Status(sub.status)
    if (
        traffic_bytes
        and sub.traffic_limit_bytes is not None
        and (status in LIVE or status is Status.EXHAUSTED)
    ):
        after = state_mod.grant_traffic(to_state(sub), traffic_bytes, now)
        _write(sub, after)
        if _revived_from_exhausted(status, after):
            await bus.record(session, TrafficReset(client_id=client_id))
    await session.flush()


async def find_client_by_referral_code(session: AsyncSession, code: str) -> Client | None:
    client: Client | None = await session.scalar(
        select(Client).where(Client.referral_code == code.lower())
    )
    return client


async def set_referrer(session: AsyncSession, client_id: int, code: str) -> bool:
    """Привязывает клиента к пригласившему. Один раз: уже привязанного не переписывает;
    неизвестный код и «пригласить себя» молча игнорируются. True — привязка появилась."""
    client = await get_client(session, client_id)
    if client.referred_by is not None:
        return False
    referrer = await find_client_by_referral_code(session, code)
    if referrer is None or referrer.id == client.id:
        return False
    client.referred_by = referrer.id
    await session.flush()
    return True


# --- журнал наград -------------------------------------------------------------


async def reward_exists_for_payment(session: AsyncSession, payment_id: int) -> bool:
    found = await session.scalar(
        select(ReferralReward.id).where(
            ReferralReward.payment_id == payment_id, ReferralReward.kind == "base"
        )
    )
    return found is not None


async def recent_base_rewards(session: AsyncSession, inviter_id: int, since: datetime) -> int:
    """Базовые награды с днями за период (для потолка). Урезанные потолком не считаются."""
    count = await session.scalar(
        select(func.count())
        .select_from(ReferralReward)
        .where(
            ReferralReward.inviter_id == inviter_id,
            ReferralReward.kind == "base",
            ReferralReward.status != "capped",
            ReferralReward.created_at >= since,
        )
    )
    return int(count or 0)


async def paying_friends(session: AsyncSession, inviter_id: int) -> int:
    """Сколько приглашённых заплатили: по одной базовой награде на друга, в том числе урезанной."""
    count = await session.scalar(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.inviter_id == inviter_id, ReferralReward.kind == "base")
    )
    return int(count or 0)


async def tier_rewarded(session: AsyncSession, inviter_id: int, tier: int) -> bool:
    found = await session.scalar(
        select(ReferralReward.id).where(
            ReferralReward.inviter_id == inviter_id,
            ReferralReward.kind == "tier",
            ReferralReward.tier == tier,
        )
    )
    return found is not None


async def add_reward(session: AsyncSession, **fields: Any) -> ReferralReward:
    row = ReferralReward(**fields)
    session.add(row)
    await session.flush()
    return row


async def pending_rewards(session: AsyncSession, inviter_id: int) -> list[ReferralReward]:
    return list(
        await session.scalars(
            select(ReferralReward)
            .where(ReferralReward.inviter_id == inviter_id, ReferralReward.status == "pending")
            .order_by(ReferralReward.id)
            .with_for_update()
        )
    )
