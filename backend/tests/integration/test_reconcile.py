import pytest
from cryptography import x509
from sqlalchemy import select

from ocmanager.audit.models import AuditLog
from ocmanager.nodes import files
from tests.integration.env import Env

pytestmark = pytest.mark.ocserv


async def test_reconcile_heals_a_damaged_node(env: Env) -> None:
    await env.paid_client(5001)
    issued = await env.issue_device(5001)
    state = env.settings.ocserv_state_dir

    (state / "allowed.list").write_text("c999-d1\n")  # чужой username вместо нашего
    (state / "crl.pem").unlink()

    out = await env.cli("reconcile")
    assert "allowlist_diff" in out
    assert "crl_missing" in out
    assert files.parse_allowlist((state / "allowed.list").read_bytes()) == {issued.cert.cn}
    x509.load_pem_x509_crl((state / "crl.pem").read_bytes())

    async with env.sessionmaker() as session:
        actions = set(
            await session.scalars(
                select(AuditLog.action).where(AuditLog.action.like("reconcile.%"))
            )
        )
    assert {"reconcile.allowlist_diff", "reconcile.crl_missing"} <= actions

    assert "расхождений нет" in await env.cli("reconcile")  # второй проход чист
    await env.vpn.connect(issued.cert)  # и нода действительно рабочая
