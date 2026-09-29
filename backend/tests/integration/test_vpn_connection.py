"""Главный сценарий продукта (спека §13): клиент с подпиской получает устройство
из CLI и подключается к живому ocserv."""

import pytest

from tests.integration.env import Env

pytestmark = pytest.mark.ocserv


async def test_paid_client_connects(env: Env) -> None:
    await env.paid_client(5001)
    issued = await env.issue_device(5001)
    await env.vpn.connect(issued.cert)
    await env.vpn.ping(issued.cert.cn, "10.77.0.1", count=3, size=1000)

    await env.collect_traffic()
    log = await env.session_log(issued.cert.cn)
    assert log is not None
    assert log.bytes_in >= 3000
    assert (await env.subscription()).traffic_used_bytes >= 6000  # туда и обратно


async def test_device_of_an_unpaid_client_is_never_issued(env: Env) -> None:
    await env.cli("client", "add", "--telegram-id", "5002", "--first-name", "Free")
    with pytest.raises(AssertionError, match="subscription_inactive"):
        await env.issue_device(5002)
