import pytest

from tests.integration.env import Env

pytestmark = pytest.mark.ocserv


async def test_revoked_device_is_dropped_and_rejected_but_its_sibling_works(env: Env) -> None:
    await env.paid_client(5001)
    first = await env.issue_device(5001, "phone", "ios")
    second = await env.issue_device(5001, "laptop", "linux")
    await env.vpn.connect(first.cert)

    await env.cli("device", "revoke", str(first.device_id))
    await env.eventually_disconnected(first.cert.cn)
    assert not await env.vpn.authenticate_only(first.cert)  # отказ по CRL, а не по allowlist

    await env.vpn.connect(second.cert)  # соседнее устройство того же клиента не задето
