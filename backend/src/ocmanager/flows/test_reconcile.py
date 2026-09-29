from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from conftest import MakeClient, MakeDevice, MakeSubscription
from cryptography import x509
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.config import Settings
from ocmanager.flows import reconcile
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node
from ocmanager.provisioning import revocations, service
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.crl import build_crl

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture
async def node(session: AsyncSession, settings: Settings) -> Node:
    return await registry.ensure_local_node(session, settings)


@pytest.fixture
def healthy(test_ca: CertificateAuthority) -> FakeNodeDriver:
    """Нода в идеальном состоянии для пустой БД: пустой allowlist и свежий пустой CRL."""
    return FakeNodeDriver(allowlist=set(), crl=build_crl(test_ca, [], NOW))


def writes(fake: FakeNodeDriver) -> list[str]:
    changing = {"publish_allowlist", "publish_crl", "reload", "disconnect_user"}
    return [name for name, _ in fake.calls if name in changing]


def kinds(report: reconcile.ReconcileReport) -> list[str]:
    return [d.kind for d in report.drifts]


async def run(
    session: AsyncSession, node: Node, fake: FakeNodeDriver, ca: CertificateAuthority
) -> reconcile.ReconcileReport:
    return await reconcile.reconcile_node(session, node, fake, ca, NOW)


def serials(pem: bytes | None) -> set[int]:
    assert pem is not None
    return {r.serial_number for r in x509.load_pem_x509_crl(pem)}


async def revoke(session: AsyncSession, device: Device, *, applied: bool) -> int:
    await service.revoke_device(session, device.id, owner_client_id=None, reason="x", now=NOW)
    if applied:
        await revocations.mark_applied(
            session, [p.id for p in await revocations.pending_revocations(session)], NOW
        )
    return int(device.cert_serial, 16)


async def test_clean_node_means_no_drift_and_no_writes(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    report = await run(session, node, healthy, test_ca)
    assert (report.drifts, report.error) == ((), None)
    assert writes(healthy) == []


async def test_missing_allowlist_is_restored(
    session: AsyncSession,
    node: Node,
    healthy: FakeNodeDriver,
    test_ca: CertificateAuthority,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    username = (await make_device(client)).ocserv_username
    healthy.allowlist = None
    report = await run(session, node, healthy, test_ca)
    assert kinds(report) == ["allowlist_missing"]
    assert report.drifts[0].details == {"added": [username]}
    assert healthy.allowlist == {username}


async def test_extra_username_is_removed_and_its_session_dropped(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.allowlist = {"c999-d1"}
    healthy.add_session("c999-d1")
    report = await run(session, node, healthy, test_ca)
    assert kinds(report) == ["allowlist_diff", "rogue_session"]
    assert report.drifts[0].details == {"added": [], "removed": ["c999-d1"]}
    assert report.drifts[1].details == {"usernames": ["c999-d1"]}
    assert (healthy.allowlist, healthy.sessions) == (set(), [])


async def test_rogue_session_alone(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.add_session("c5-d1")  # в allowlist его нет, но сессия каким-то образом жива
    assert kinds(await run(session, node, healthy, test_ca)) == ["rogue_session"]


async def test_missing_crl_is_published_and_reloaded(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.crl = None
    report = await run(session, node, healthy, test_ca)
    assert kinds(report) == ["crl_missing"]
    assert report.drifts[0].details == {"reason": "absent"}
    assert healthy.crl is not None
    assert "reload" in writes(healthy)


async def test_unreadable_crl_is_replaced(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.crl = b"not a crl"
    report = await run(session, node, healthy, test_ca)
    assert report.drifts[0].kind == "crl_missing"
    assert report.drifts[0].details == {"reason": "unreadable"}
    assert serials(healthy.crl) == set()  # разобрался как настоящий пустой CRL


async def test_crl_without_an_applied_revocation(
    session: AsyncSession,
    node: Node,
    healthy: FakeNodeDriver,
    test_ca: CertificateAuthority,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    device = await make_device(await make_client())
    serial = await revoke(session, device, applied=True)
    report = await run(session, node, healthy, test_ca)
    assert kinds(report) == ["crl_diff"]
    assert report.drifts[0].details == {"missing": [format(serial, "x")], "unknown": []}
    assert serials(healthy.crl) == {serial}
    assert "reload" in writes(healthy)


async def test_crl_with_an_unknown_serial(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.crl = build_crl(test_ca, [(0xABC, NOW)], NOW)
    report = await run(session, node, healthy, test_ca)
    assert report.drifts[0].details == {"missing": [], "unknown": ["abc"]}
    assert serials(healthy.crl) == set()


async def test_revocation_still_waiting_for_its_cron_is_not_a_drift(
    session: AsyncSession,
    node: Node,
    healthy: FakeNodeDriver,
    test_ca: CertificateAuthority,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    device = await make_device(await make_client())
    await revoke(session, device, applied=False)
    report = await run(session, node, healthy, test_ca)
    assert report.drifts == ()
    assert writes(healthy) == []


async def test_republishing_never_drops_a_pending_revocation(
    session: AsyncSession,
    node: Node,
    healthy: FakeNodeDriver,
    test_ca: CertificateAuthority,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    applied = await revoke(session, await make_device(client, seq=1), applied=True)
    pending = await revoke(session, await make_device(client, seq=2), applied=False)
    await run(session, node, healthy, test_ca)  # crl_diff → публикуется полный набор
    assert serials(healthy.crl) == {applied, pending}


async def test_crl_close_to_expiry_is_renewed(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.crl = build_crl(test_ca, [], NOW - 5 * DAY)  # next_update через 2 дня
    report = await run(session, node, healthy, test_ca)
    assert kinds(report) == ["crl_expiring"]
    assert healthy.crl is not None
    assert x509.load_pem_x509_crl(healthy.crl).next_update_utc == NOW + 7 * DAY


async def test_stopped_container_is_reported_and_nothing_is_touched(
    session: AsyncSession, node: Node, test_ca: CertificateAuthority
) -> None:
    fake = FakeNodeDriver(allowlist=None, crl=None, container_state="exited")
    report = await run(session, node, fake, test_ca)
    assert (report.drifts, report.error) == ((), "container exited")
    assert writes(fake) == []
    assert node.last_reconcile_report is not None
    assert node.last_reconcile_report["error"] == "container exited"


async def test_silent_occtl_still_fixes_files_and_reports_the_error(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.allowlist = None
    healthy.occtl_ok = False
    report = await run(session, node, healthy, test_ca)
    assert healthy.allowlist == set()  # файл починен
    assert kinds(report) == ["allowlist_missing"]
    assert report.error is not None
    assert "occtl" in report.error
    assert len(await audit_rows(session)) == 1  # найденный дрейф записан несмотря на сбой


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


async def test_report_is_stored_on_the_node_and_every_drift_is_audited(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.allowlist = {"c999-d1"}
    healthy.crl = None
    with time_machine.travel(NOW + timedelta(seconds=2), tick=False):
        report = await run(session, node, healthy, test_ca)
    assert (report.started_at, report.finished_at) == (NOW, NOW + timedelta(seconds=2))
    assert node.last_reconcile_at == report.finished_at
    stored = node.last_reconcile_report
    assert stored is not None
    assert [d["kind"] for d in stored["drifts"]] == ["allowlist_diff", "crl_missing"]
    assert stored["error"] is None
    rows = await audit_rows(session)
    assert [(r.actor_type, r.action, r.target_type, r.target_id) for r in rows] == [
        ("system", "reconcile.allowlist_diff", "node", str(node.id)),
        ("system", "reconcile.crl_missing", "node", str(node.id)),
    ]


async def test_second_run_converges(
    session: AsyncSession, node: Node, healthy: FakeNodeDriver, test_ca: CertificateAuthority
) -> None:
    healthy.allowlist = {"c999-d1"}
    healthy.crl = None
    healthy.add_session("c999-d1")
    assert (await run(session, node, healthy, test_ca)).drifts
    healthy.calls.clear()
    assert (await run(session, node, healthy, test_ca)).drifts == ()
    assert writes(healthy) == []


async def test_reconcile_all(
    session: AsyncSession,
    settings: Settings,
    healthy: FakeNodeDriver,
    test_ca: CertificateAuthority,
) -> None:
    with registry.override_driver(healthy):
        [report] = await reconcile.reconcile_all(session, settings, test_ca, NOW)
    assert report.drifts == ()
