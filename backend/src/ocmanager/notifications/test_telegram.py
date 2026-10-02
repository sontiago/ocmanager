import json
import logging

import httpx
import pytest

from ocmanager.notifications.telegram import SendOutcome, send_message

TOKEN = "123456:secret-bot-token"


def client(handler: httpx.MockTransport | None = None, **response: object) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(**response)  # type: ignore[arg-type]

    return httpx.AsyncClient(transport=handler or httpx.MockTransport(respond))


async def test_ok_is_sent_and_the_request_has_chat_and_text() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with client(httpx.MockTransport(respond)) as http:
        result = await send_message(http, TOKEN, 42, "Привет")

    assert result.outcome is SendOutcome.SENT
    [request] = seen
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert json.loads(request.content) == {"chat_id": 42, "text": "Привет"}


async def test_429_is_a_retry_with_the_pause_telegram_asked_for() -> None:
    body = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 7",
        "parameters": {"retry_after": 7},
    }
    async with client(status_code=429, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert (result.outcome, result.retry_after) == (SendOutcome.RETRY, 7)


async def test_429_without_a_pause_is_an_ordinary_retry() -> None:
    async with client(status_code=429, json={"ok": False}) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert (result.outcome, result.retry_after) == (SendOutcome.RETRY, None)


async def test_a_blocked_bot_is_undeliverable() -> None:
    body = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
    async with client(status_code=403, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.UNDELIVERABLE
    assert result.error is not None
    assert "blocked" in result.error


async def test_chat_not_found_is_undeliverable() -> None:
    body = {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    async with client(status_code=400, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.UNDELIVERABLE


@pytest.mark.parametrize("status", [400, 401, 500, 502])
async def test_other_failures_are_retried(status: int) -> None:
    async with client(status_code=status, json={"ok": False, "description": "boom"}) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY
    assert result.retry_after is None


async def test_a_non_json_error_body_is_a_retry() -> None:
    async with client(status_code=502, text="<html>Bad Gateway</html>") as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY


async def test_a_network_error_is_a_retry_and_does_not_leak_the_token() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with client(httpx.MockTransport(boom)) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY
    assert result.error == "ConnectError"
    assert TOKEN not in (result.error or "")


async def test_the_token_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        async with client(status_code=200, json={"ok": True}) as http:
            await send_message(http, TOKEN, 42, "x")
    assert TOKEN not in caplog.text
