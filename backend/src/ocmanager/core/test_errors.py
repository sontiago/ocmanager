import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel

from ocmanager.core import errors
from ocmanager.core.errors import install_error_handlers


class Body(BaseModel):
    name: str


def make_app(exc: Exception | None = None) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        assert exc is not None
        raise exc

    @app.post("/echo")
    async def echo(body: Body) -> Body:
        return body

    return app


async def request(app: FastAPI, method: str, url: str, **kwargs: object) -> Response:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.request(method, url, **kwargs)  # type: ignore[arg-type]


async def boom(exc: Exception) -> Response:
    return await request(make_app(exc), "GET", "/boom")


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (errors.Unauthorized(), 401, "unauthorized"),
        (errors.InitDataExpired(), 401, "initdata_expired"),
        (errors.Forbidden(), 403, "forbidden"),
        (errors.NotFound(), 404, "not_found"),
        (errors.Conflict(), 409, "conflict"),
        (errors.InvalidTransition(), 409, "invalid_transition"),
        (errors.DeviceLimitReached(), 409, "device_limit_reached"),
        (errors.TrialAlreadyUsed(), 409, "trial_already_used"),
        (errors.SubscriptionInactive(), 409, "subscription_inactive"),
        (errors.InvalidInput(), 422, "validation_error"),
        (errors.RateLimited(retry_after=1), 429, "rate_limited"),
        (errors.NodeUnavailable(), 503, "node_unavailable"),
    ],
)
async def test_domain_error_envelope(exc: errors.DomainError, status: int, code: str) -> None:
    r = await boom(exc)
    assert r.status_code == status
    assert r.json() == {"error": {"code": code, "message": code}}


async def test_custom_message() -> None:
    r = await boom(errors.Conflict("plan code taken"))
    assert r.json()["error"] == {"code": "conflict", "message": "plan code taken"}


async def test_blocked_is_403() -> None:
    r = await boom(errors.SubscriptionInactive(blocked=True))
    assert (r.status_code, r.json()["error"]["code"]) == (403, "subscription_inactive")


async def test_rate_limited_sets_retry_after() -> None:
    r = await boom(errors.RateLimited(retry_after=17))
    assert r.headers["Retry-After"] == "17"


async def test_unexpected_exception_hides_details() -> None:
    r = await boom(RuntimeError("password=hunter2"))
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal", "message": "internal"}}


async def test_request_validation_is_validation_error() -> None:
    r = await request(make_app(), "POST", "/echo", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["message"].startswith("name: ")


async def test_unknown_route_is_not_found() -> None:
    r = await request(make_app(), "GET", "/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "not_found"}}


async def test_wrong_method_is_not_found_with_405() -> None:
    r = await request(make_app(), "DELETE", "/echo")
    assert (r.status_code, r.json()["error"]["code"]) == (405, "not_found")
