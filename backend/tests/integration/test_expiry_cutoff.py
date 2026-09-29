import pytest

from tests.integration.env import Env
from tests.integration.stand import ConnectFailed

pytestmark = pytest.mark.ocserv


async def test_expiry_cuts_off_and_renewal_restores_the_same_certificate(env: Env) -> None:
    await env.paid_client(5001)
    issued = await env.issue_device(5001)
    await env.vpn.connect(issued.cert)

    await env.cli("subscription", "expire-now", "5001")
    await env.eventually_disconnected(issued.cert.cn)
    with pytest.raises(ConnectFailed):
        await env.vpn.connect(issued.cert)

    await env.cli("client", "grant", "5001", "m1")  # продление: перевыпуск не нужен
    await env.vpn.connect(issued.cert)
