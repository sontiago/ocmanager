from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.core import settings_store
from ocmanager.core.errors import NotFound, TrialAlreadyUsed
from ocmanager.flows import trial

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
GIB = 1024**3
ACTOR = Actor("client", "1")


async def test_trial_takes_its_terms_from_runtime_settings(
    session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    client = await make_client()
    sub = await trial.start_trial(session, client_id=client.id, actor=ACTOR, now=NOW)
    assert (sub.status, sub.plan_is_trial, sub.auto_renew) == ("trial", True, False)
    assert sub.expires_at == NOW + timedelta(days=3)  # RuntimeSettings.trial_days
    assert (sub.traffic_limit_bytes, sub.device_limit) == (5 * GIB, 1)
    assert sub.plan_id == trial_plan.id


async def test_changed_settings_apply_to_the_next_trial(
    session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    await settings_store.update(session, {"trial_days": 7, "trial_traffic_bytes": 0})
    sub = await trial.start_trial(session, client_id=(await make_client()).id, actor=ACTOR, now=NOW)
    assert sub.expires_at == NOW + timedelta(days=7)
    assert sub.traffic_limit_bytes is None  # 0 = без лимита


async def test_trial_only_once_and_audited_once(
    session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    client = await make_client()
    await trial.start_trial(session, client_id=client.id, actor=ACTOR, now=NOW)
    with pytest.raises(TrialAlreadyUsed):
        await trial.start_trial(session, client_id=client.id, actor=ACTOR, now=NOW)
    rows = list(await session.scalars(select(AuditLog).where(AuditLog.target_type == "client")))
    assert [r.action for r in rows] == ["subscription.start_trial"]


async def test_missing_trial_plan_is_reported(
    session: AsyncSession, make_client: MakeClient
) -> None:
    await session.execute(text("DELETE FROM plans"))
    with pytest.raises(NotFound):
        await trial.start_trial(session, client_id=(await make_client()).id, actor=ACTOR, now=NOW)
