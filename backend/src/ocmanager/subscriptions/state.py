"""Автомат подписки — чистые функции, без БД, времени и сети.

Каждая команда принимает текущее состояние (None — подписки ещё нет) и
возвращает новое; ничего не мутирует. Время передаётся параметром. Переход,
которого нет в таблице (дорожная карта, Задача 2.2), — InvalidTransition.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from ocmanager.core.errors import InvalidInput, InvalidTransition


class Status(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# Потолок ручного продления; совпадает с billing.plans.MAX_DURATION_DAYS
# (scripts/test_consistency.py). Больше — риск выйти за 9999 год и получить OverflowError.
MAX_DAYS: Final = 3650

# Дают доступ. cancelled — это auto_renew=false при живом expires_at.
LIVE: Final = frozenset({Status.TRIAL, Status.ACTIVE, Status.CANCELLED})


@dataclass(frozen=True)
class PlanTerms:
    """Условия тарифа на момент операции. Строится в flows/ из billing.Plan
    (subscriptions не импортирует billing)."""

    plan_id: int
    duration_days: int
    device_limit: int
    traffic_limit_bytes: int | None
    is_trial: bool


@dataclass(frozen=True)
class SubState:
    status: Status
    plan_id: int
    plan_is_trial: bool
    started_at: datetime
    expires_at: datetime
    auto_renew: bool
    device_limit: int
    traffic_limit_bytes: int | None
    traffic_period_start: datetime
    traffic_used_bytes: int


def _new(
    terms: PlanTerms,
    now: datetime,
    *,
    status: Status,
    expires_at: datetime,
    auto_renew: bool,
) -> SubState:
    return SubState(
        status=status,
        plan_id=terms.plan_id,
        plan_is_trial=terms.is_trial,
        started_at=now,
        expires_at=expires_at,
        auto_renew=auto_renew,
        device_limit=terms.device_limit,
        traffic_limit_bytes=terms.traffic_limit_bytes,
        traffic_period_start=now,
        traffic_used_bytes=0,
    )


def _refuse(action: str, current: SubState | None) -> InvalidTransition:
    where = "no subscription" if current is None else current.status.value
    return InvalidTransition(f"cannot {action} from {where}")


def start_trial(current: SubState | None, terms: PlanTerms, now: datetime) -> SubState:
    if current is not None:
        raise _refuse("start trial", current)
    expires_at = now + timedelta(days=terms.duration_days)
    return _new(terms, now, status=Status.TRIAL, expires_at=expires_at, auto_renew=False)


def _extend(current: SubState, terms: PlanTerms, now: datetime, *, auto_renew: bool) -> SubState:
    """Продление живой подписки: дни добавляются к концу оплаченного срока, а если
    cron истечения отстал и срок уже прошёл — считаются от now (клиент не теряет дни).
    """
    base = max(current.expires_at, now)
    return replace(
        current,
        status=Status.ACTIVE,
        plan_id=terms.plan_id,
        plan_is_trial=terms.is_trial,
        expires_at=base + timedelta(days=terms.duration_days),
        auto_renew=auto_renew,
        device_limit=terms.device_limit,
        traffic_limit_bytes=terms.traffic_limit_bytes,
        traffic_period_start=now,
        traffic_used_bytes=0,
    )


_RESTART_FROM: Final = frozenset(
    {Status.PENDING_PAYMENT, Status.TRIAL, Status.EXPIRED, Status.EXHAUSTED}
)


def _restart(terms: PlanTerms, now: datetime, *, auto_renew: bool) -> SubState:
    expires_at = now + timedelta(days=terms.duration_days)
    return _new(terms, now, status=Status.ACTIVE, expires_at=expires_at, auto_renew=auto_renew)


def activate(
    current: SubState | None, terms: PlanTerms, now: datetime, *, auto_renew: bool
) -> SubState:
    """Выдача или покупка тарифа. Остаток trial сгорает (решение №14)."""
    if current is None or current.status in _RESTART_FROM:
        return _restart(terms, now, auto_renew=auto_renew)
    if current.status in {Status.ACTIVE, Status.CANCELLED}:
        return _extend(current, terms, now, auto_renew=auto_renew)
    raise _refuse("activate", current)


def renew(current: SubState | None, terms: PlanTerms, now: datetime) -> SubState:
    """Оплаченное продление: всегда включает автопродление."""
    if current is None or current.status in _RESTART_FROM - {Status.PENDING_PAYMENT}:
        return _restart(terms, now, auto_renew=True)
    if current.status in {Status.ACTIVE, Status.CANCELLED}:
        return _extend(current, terms, now, auto_renew=True)
    raise _refuse("renew", current)


def extend(current: SubState, days: int, now: datetime) -> SubState:
    """Ручное продление из админки: дни без смены тарифа и без оплаты.
    Живая и заблокированная подписки сдвигают срок; истёкшая начинается заново
    от now и оживает без автопродления (trial остаётся trial)."""
    if not 0 < days <= MAX_DAYS:
        raise InvalidInput(f"days must be 1..{MAX_DAYS}")
    if current.status is Status.PENDING_PAYMENT:
        raise _refuse("extend", current)
    if current.status in LIVE or current.status is Status.BLOCKED:
        return replace(current, expires_at=max(current.expires_at, now) + timedelta(days=days))
    revived = Status.TRIAL if current.plan_is_trial else Status.CANCELLED
    return replace(current, status=revived, auto_renew=False, expires_at=now + timedelta(days=days))


def cancel_auto_renew(current: SubState) -> SubState:
    """Идемпотентно: Tribute может прислать отмену уже после истечения."""
    if current.status is Status.ACTIVE:
        return replace(current, status=Status.CANCELLED, auto_renew=False)
    return current


def expire(current: SubState, now: datetime) -> SubState:
    if current.status is Status.EXPIRED:
        return current
    if current.status in LIVE and current.expires_at <= now:
        return replace(current, status=Status.EXPIRED)
    raise _refuse("expire", current)


def expire_now(current: SubState, now: datetime) -> SubState:
    """Досрочное истечение — вручную, при злоупотреблении. Срок обрезается до `now`:
    иначе статус `expired` и `expires_at` в будущем расходились бы, а страховка
    `expires_at > now` в списке доступа считала бы клиента живым."""
    if current.status not in LIVE:
        raise _refuse("expire now", current)
    return replace(current, status=Status.EXPIRED, expires_at=min(current.expires_at, now))


def block(current: SubState) -> SubState:
    return replace(current, status=Status.BLOCKED)


def unblock(current: SubState, now: datetime) -> SubState:
    """Статус выводится заново по сроку (решение №13): «до блокировки» не хранится."""
    if current.status is not Status.BLOCKED:
        raise _refuse("unblock", current)
    if current.expires_at <= now:
        return replace(current, status=Status.EXPIRED)
    if current.plan_is_trial:
        return replace(current, status=Status.TRIAL)
    return replace(current, status=Status.ACTIVE if current.auto_renew else Status.CANCELLED)


def has_access(state: SubState | None, *, client_blocked: bool, now: datetime) -> bool:
    """Последнее условие — страховка: даже если cron истечения отстал, по времени доступ закрыт."""
    return (
        state is not None and state.status in LIVE and not client_blocked and state.expires_at > now
    )
