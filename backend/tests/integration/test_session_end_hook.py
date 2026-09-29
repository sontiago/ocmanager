import pytest

from tests.integration.env import Env

pytestmark = pytest.mark.ocserv


async def test_hook_alone_counts_a_session_nobody_polled(env: Env) -> None:
    """«Слепая» сессия: опроса между подключением и отключением не было (спека §5)."""
    await env.paid_client(5001)
    issued = await env.issue_device(5001)
    await env.vpn.connect(issued.cert)
    await env.vpn.ping(issued.cert.cn, "10.77.0.1", count=3, size=1000)

    await env.stop_client_gracefully(issued.cert.cn)
    log = await env.eventually_final(issued.cert.cn, within=15)

    assert log.ended_at is not None
    assert log.bytes_in >= 3000  # ни один байт не потерян, хотя опроса между ними не было
    assert (await env.subscription()).traffic_used_bytes >= 6000


async def test_hook_after_a_poll_adds_only_the_tail(env: Env) -> None:
    await env.paid_client(5001)
    issued = await env.issue_device(5001)
    await env.vpn.connect(issued.cert)
    await env.vpn.ping(issued.cert.cn, "10.77.0.1", count=3, size=1000)
    await env.collect_traffic()
    polled = await env.counted_bytes_in(issued.cert.cn)
    assert polled >= 3000

    await env.vpn.ping(issued.cert.cn, "10.77.0.1", count=2, size=1000)  # после опроса
    await env.stop_client_gracefully(issued.cert.cn)
    log = await env.eventually_final(issued.cert.cn, within=15)

    assert log.bytes_in >= 5000
    # Ни потерь, ни двойного счёта: учтено ровно то, что насчитал ocserv к отключению.
    assert await env.counted_bytes_in(issued.cert.cn) == log.bytes_in
