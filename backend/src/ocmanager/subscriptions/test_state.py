from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ocmanager.core.errors import InvalidInput, InvalidTransition
from ocmanager.subscriptions.state import (
    LIVE,
    MAX_DAYS,
    PlanTerms,
    Status,
    SubState,
    activate,
    block,
    cancel_auto_renew,
    expire,
    expire_now,
    extend,
    has_access,
    renew,
    start_trial,
    unblock,
)

GIB = 1024**3
NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)

MONTH = PlanTerms(
    plan_id=2,
    duration_days=30,
    device_limit=3,
    traffic_limit_bytes=100 * GIB,
    is_trial=False,
)
TRIAL = PlanTerms(
    plan_id=1,
    duration_days=3,
    device_limit=1,
    traffic_limit_bytes=5 * GIB,
    is_trial=True,
)


def sub(status: Status, **over: object) -> SubState:
    """Подписка в заданном статусе: оплачена 10 дней назад, действует ещё 20."""
    base = SubState(
        status=status,
        plan_id=2,
        plan_is_trial=False,
        started_at=NOW - 10 * DAY,
        expires_at=NOW + 20 * DAY,
        auto_renew=status is Status.ACTIVE,
        device_limit=3,
        traffic_limit_bytes=100 * GIB,
        traffic_period_start=NOW - 10 * DAY,
        traffic_used_bytes=7 * GIB,
    )
    return replace(base, **over)  # type: ignore[arg-type]


ALL = list(Status)
LIVE_STATUSES = [Status.ACTIVE, Status.CANCELLED]


# --- start_trial -----------------------------------------------------------


def test_start_trial_from_nothing() -> None:
    s = start_trial(None, TRIAL, NOW)
    assert (s.status, s.plan_is_trial, s.auto_renew) == (Status.TRIAL, True, False)
    assert s.expires_at == NOW + 3 * DAY
    assert (s.device_limit, s.traffic_limit_bytes) == (1, 5 * GIB)
    assert (s.traffic_used_bytes, s.traffic_period_start, s.started_at) == (0, NOW, NOW)


@pytest.mark.parametrize("status", ALL)
def test_start_trial_only_without_subscription(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        start_trial(sub(status), TRIAL, NOW)


# --- activate --------------------------------------------------------------


@pytest.mark.parametrize(
    "current",
    [
        None,
        sub(Status.PENDING_PAYMENT),
        sub(Status.TRIAL, plan_is_trial=True),
        sub(Status.EXPIRED, expires_at=NOW - DAY),
        sub(Status.EXHAUSTED),
    ],
)
def test_activate_starts_from_now(current: SubState | None) -> None:
    s = activate(current, MONTH, NOW, auto_renew=True)
    assert s.status is Status.ACTIVE
    assert s.expires_at == NOW + 30 * DAY
    assert (s.started_at, s.traffic_period_start, s.traffic_used_bytes) == (NOW, NOW, 0)
    assert (s.plan_id, s.device_limit, s.traffic_limit_bytes) == (2, 3, 100 * GIB)
    assert not s.plan_is_trial


@pytest.mark.parametrize("current", LIVE_STATUSES)
def test_activate_live_extends_from_expiry(current: Status) -> None:
    before = sub(current)
    s = activate(before, MONTH, NOW, auto_renew=False)
    assert s.status is Status.ACTIVE
    assert s.expires_at == before.expires_at + 30 * DAY
    assert s.started_at == before.started_at
    assert s.auto_renew is False  # ручная выдача не включает автопродление
    assert s.traffic_used_bytes == 0


@pytest.mark.parametrize("auto_renew", [True, False])
def test_activate_honours_auto_renew(auto_renew: bool) -> None:
    assert activate(None, MONTH, NOW, auto_renew=auto_renew).auto_renew is auto_renew


def test_activate_blocked_is_refused() -> None:
    with pytest.raises(InvalidTransition):
        activate(sub(Status.BLOCKED), MONTH, NOW, auto_renew=True)


def test_trial_to_paid_drops_trial_remainder() -> None:
    trial = start_trial(None, TRIAL, NOW)
    paid = activate(trial, MONTH, NOW + DAY, auto_renew=True)
    assert paid.expires_at == NOW + 31 * DAY
    assert (paid.device_limit, paid.plan_is_trial) == (3, False)


# --- renew -----------------------------------------------------------------


def test_renew_extends_from_expiry_not_from_now() -> None:
    s = activate(None, MONTH, NOW, auto_renew=True)
    s2 = renew(s, MONTH, NOW + 10 * DAY)
    assert s2.expires_at == NOW + 60 * DAY


def test_renew_of_lapsed_but_not_yet_expired_counts_from_now() -> None:
    """Cron истечения отстал: подписка ещё active, но срок вышел час назад."""
    lapsed = sub(Status.ACTIVE, expires_at=NOW - timedelta(hours=1))
    assert renew(lapsed, MONTH, NOW).expires_at == NOW + 30 * DAY


@pytest.mark.parametrize("current", LIVE_STATUSES)
def test_renew_live_turns_auto_renew_on(current: Status) -> None:
    s = renew(sub(current, auto_renew=False), MONTH, NOW)
    assert (s.status, s.auto_renew) == (Status.ACTIVE, True)


def test_renew_resets_traffic_period() -> None:
    s = replace(activate(None, MONTH, NOW, auto_renew=True), traffic_used_bytes=5 * GIB)
    later = NOW + 29 * DAY
    s2 = renew(s, MONTH, later)
    assert (s2.traffic_used_bytes, s2.traffic_period_start) == (0, later)


def test_renew_applies_new_plan_limits() -> None:
    bigger = PlanTerms(3, 30, 5, None, False)
    s = renew(sub(Status.ACTIVE), bigger, NOW)
    assert (s.plan_id, s.device_limit, s.traffic_limit_bytes) == (3, 5, None)


@pytest.mark.parametrize(
    "current",
    [
        None,
        sub(Status.TRIAL, plan_is_trial=True),
        sub(Status.EXPIRED, expires_at=NOW - DAY),
        sub(Status.EXHAUSTED),
    ],
)
def test_renew_without_live_paid_period_starts_from_now(
    current: SubState | None,
) -> None:
    s = renew(current, MONTH, NOW)
    assert (s.status, s.auto_renew, s.expires_at) == (
        Status.ACTIVE,
        True,
        NOW + 30 * DAY,
    )


@pytest.mark.parametrize("status", [Status.PENDING_PAYMENT, Status.BLOCKED])
def test_renew_refused(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        renew(sub(status), MONTH, NOW)


# --- extend ----------------------------------------------------------------


@pytest.mark.parametrize("status", [*sorted(LIVE), Status.BLOCKED])
def test_extend_shifts_the_end_date_and_keeps_status(status: Status) -> None:
    before = sub(status)
    s = extend(before, 7, NOW)
    assert s.expires_at == before.expires_at + 7 * DAY
    assert (s.status, s.auto_renew, s.plan_id, s.traffic_used_bytes) == (
        before.status,
        before.auto_renew,
        before.plan_id,
        before.traffic_used_bytes,
    )


def test_extend_of_lapsed_live_subscription_counts_from_now() -> None:
    lapsed = sub(Status.ACTIVE, expires_at=NOW - DAY)
    assert extend(lapsed, 7, NOW).expires_at == NOW + 7 * DAY


@pytest.mark.parametrize(
    ("current", "revived"),
    [
        (sub(Status.EXPIRED, expires_at=NOW - DAY), Status.CANCELLED),
        (sub(Status.EXPIRED, expires_at=NOW - DAY, auto_renew=True), Status.CANCELLED),
        (sub(Status.EXHAUSTED, expires_at=NOW - DAY), Status.CANCELLED),
        (sub(Status.EXPIRED, expires_at=NOW - DAY, plan_is_trial=True), Status.TRIAL),
    ],
)
def test_extend_revives_an_ended_subscription_without_auto_renew(
    current: SubState, revived: Status
) -> None:
    s = extend(current, 7, NOW)
    assert (s.status, s.auto_renew, s.expires_at) == (revived, False, NOW + 7 * DAY)
    assert has_access(s, client_blocked=False, now=NOW)


def test_extend_refused_for_pending_payment_and_non_positive_days() -> None:
    with pytest.raises(InvalidTransition):
        extend(sub(Status.PENDING_PAYMENT), 7, NOW)
    for days in (0, -3, MAX_DAYS + 1, 999_999_999):
        with pytest.raises(InvalidInput):
            extend(sub(Status.ACTIVE), days, NOW)


def test_extend_accepts_the_ceiling() -> None:
    assert extend(sub(Status.ACTIVE), MAX_DAYS, NOW).expires_at > NOW + 3650 * DAY


# --- cancel_auto_renew -----------------------------------------------------


def test_cancel_turns_auto_renew_off_and_keeps_expiry() -> None:
    before = sub(Status.ACTIVE)
    s = cancel_auto_renew(before)
    assert (s.status, s.auto_renew, s.expires_at) == (
        Status.CANCELLED,
        False,
        before.expires_at,
    )


@pytest.mark.parametrize("status", [x for x in ALL if x is not Status.ACTIVE])
def test_cancel_is_idempotent_elsewhere(status: Status) -> None:
    before = sub(status)
    assert cancel_auto_renew(before) == before


def test_cancelled_keeps_access_until_expiry() -> None:
    s = cancel_auto_renew(activate(None, MONTH, NOW, auto_renew=True))
    assert has_access(s, client_blocked=False, now=NOW + 29 * DAY)
    assert not has_access(s, client_blocked=False, now=NOW + 30 * DAY)


# --- expire ----------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(LIVE))
def test_expire_when_due(status: Status) -> None:
    due = sub(status, expires_at=NOW)
    assert expire(due, NOW).status is Status.EXPIRED


@pytest.mark.parametrize("status", sorted(LIVE))
def test_expire_before_due_is_invalid(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        expire(sub(status, expires_at=NOW + timedelta(seconds=1)), NOW)


def test_expire_is_idempotent() -> None:
    expired = sub(Status.EXPIRED, expires_at=NOW - DAY)
    assert expire(expired, NOW) == expired


@pytest.mark.parametrize("status", [Status.PENDING_PAYMENT, Status.EXHAUSTED, Status.BLOCKED])
def test_expire_refused_for_non_live(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        expire(sub(status, expires_at=NOW - DAY), NOW)


@pytest.mark.parametrize("status", sorted(LIVE))
def test_expire_now_cuts_the_term_to_now(status: Status) -> None:
    ended = expire_now(sub(status), NOW)
    assert ended.status is Status.EXPIRED
    assert ended.expires_at == NOW
    assert not has_access(ended, client_blocked=False, now=NOW)


def test_expire_now_never_extends_a_term_that_already_passed() -> None:
    lapsed = sub(Status.ACTIVE, expires_at=NOW - DAY)
    assert expire_now(lapsed, NOW).expires_at == NOW - DAY


@pytest.mark.parametrize(
    "status", [Status.PENDING_PAYMENT, Status.EXPIRED, Status.EXHAUSTED, Status.BLOCKED]
)
def test_expire_now_refused_for_non_live(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        expire_now(sub(status), NOW)


# --- block / unblock -------------------------------------------------------


@pytest.mark.parametrize("status", ALL)
def test_block_from_anywhere_keeps_expiry(status: Status) -> None:
    before = sub(status)
    s = block(before)
    assert (s.status, s.expires_at) == (Status.BLOCKED, before.expires_at)


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"plan_is_trial": True}, Status.TRIAL),
        ({"auto_renew": True}, Status.ACTIVE),
        ({"auto_renew": False}, Status.CANCELLED),
        ({"expires_at": NOW}, Status.EXPIRED),
        ({"expires_at": NOW - DAY, "plan_is_trial": True}, Status.EXPIRED),
    ],
)
def test_unblock_rederives_status(over: dict[str, object], expected: Status) -> None:
    assert unblock(sub(Status.BLOCKED, **over), NOW).status is expected


@pytest.mark.parametrize("status", [x for x in ALL if x is not Status.BLOCKED])
def test_unblock_only_from_blocked(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        unblock(sub(status), NOW)


def test_unblock_after_expiry_gives_expired() -> None:
    s = block(activate(None, MONTH, NOW, auto_renew=True))
    assert unblock(s, NOW + 31 * DAY).status is Status.EXPIRED


# --- has_access ------------------------------------------------------------


@pytest.mark.parametrize("status", ALL)
def test_only_live_statuses_give_access(status: Status) -> None:
    assert has_access(sub(status), client_blocked=False, now=NOW) is (status in LIVE)


def test_no_subscription_no_access() -> None:
    assert not has_access(None, client_blocked=False, now=NOW)


def test_blocked_client_has_no_access_even_if_live() -> None:
    s = activate(None, MONTH, NOW, auto_renew=True)
    assert not has_access(s, client_blocked=True, now=NOW)


def test_access_ends_at_expiry_even_if_status_lags() -> None:
    s = sub(Status.ACTIVE, expires_at=NOW)
    assert not has_access(s, client_blocked=False, now=NOW)
    assert has_access(s, client_blocked=False, now=NOW - timedelta(seconds=1))


def test_functions_do_not_mutate_their_input() -> None:
    before = sub(Status.ACTIVE)
    snapshot = replace(before)
    renew(before, MONTH, NOW)
    cancel_auto_renew(before)
    block(before)
    assert before == snapshot
