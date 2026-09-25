"""Доменные ошибки и их HTTP-отображение.

Формат ответа один на весь API: {"error": {"code": "<code>", "message": "<text>"}}.
Коды TMA — ровно список из frontend/tma/src/api/errors.ts; новые коды для TMA
добавляются только вместе с правкой фронтенда.
"""

from collections.abc import Mapping
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class DomainError(Exception):
    code: str = "internal"
    status: int = 500

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)

    def headers(self) -> dict[str, str] | None:
        return None


class Unauthorized(DomainError):
    code, status = "unauthorized", 401


class InitDataExpired(DomainError):
    code, status = "initdata_expired", 401


class Forbidden(DomainError):
    code, status = "forbidden", 403


class NotFound(DomainError):
    code, status = "not_found", 404


class Conflict(DomainError):
    code, status = "conflict", 409


class InvalidTransition(DomainError):
    code, status = "invalid_transition", 409


class DeviceLimitReached(DomainError):
    code, status = "device_limit_reached", 409


class TrialAlreadyUsed(DomainError):
    code, status = "trial_already_used", 409


class SubscriptionInactive(DomainError):
    """409 — подписки нет или она кончилась; 403 — клиент заблокирован."""

    code, status = "subscription_inactive", 409

    def __init__(self, message: str | None = None, *, blocked: bool = False) -> None:
        super().__init__(message)
        if blocked:
            self.status = 403


class InvalidInput(DomainError):
    code, status = "validation_error", 422


class RateLimited(DomainError):
    code, status = "rate_limited", 429

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}


class NodeUnavailable(DomainError):
    code, status = "node_unavailable", 503


def error_response(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=headers,
    )


HTTP_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "not_found",
}


def _first_validation_message(errors: Any) -> str:
    try:
        first = errors[0]
        loc = ".".join(str(p) for p in first["loc"] if p != "body")
        return f"{loc}: {first['msg']}" if loc else str(first["msg"])
    except (IndexError, KeyError, TypeError):
        return "validation_error"


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return error_response(exc.status, exc.code, exc.message, exc.headers())


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, "validation_error", _first_validation_message(exc.errors()))


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = HTTP_STATUS_CODES.get(exc.status_code, "internal")
    return error_response(exc.status_code, code, code, exc.headers)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, exc_info=exc)
    return error_response(500, "internal", "internal")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
