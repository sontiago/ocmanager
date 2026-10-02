"""Коды ошибок и маршруты бэкенда против контракта frontend/tma/src/api/.

Код, который бэкенд отдаёт, а фронтенд не знает, у клиента превращается в `internal`
(повторяемая ошибка сервера), и человек видит не ту причину. Тест ловит расхождение до релиза.
"""

import re
from pathlib import Path

import pytest
from conftest import TmaHeaders
from httpx import AsyncClient

import ocmanager.apps.admin_api  # noqa: F401 — подключает ошибки админки, чтобы сверка была полной
from ocmanager.billing.models import Plan
from ocmanager.core.errors import DomainError

REPO = Path(__file__).resolve().parents[4]
ERRORS_TS = REPO / "frontend" / "tma" / "src" / "api" / "errors.ts"

# Коды, которых нет во фронтенде, но бэкенд может их отдать на /api/tma/*. Каждый — с причиной.
KNOWN_UNMAPPED = {
    "validation_error": "битое тело запроса; форма фронтенда таких не шлёт (maxLength=40)",
    "pki_not_ready": "не создан CA (`ocmanager pki init`): ошибка развёртывания, не пользователя",
}
# Коды только админки: до Mini App не доходят.
ADMIN_ONLY = {"forbidden", "conflict", "invalid_transition", "csrf_failed", "totp_required"}
# Есть во фронтенде, но бэкенд их сам не порождает: сеть — на стороне клиента, internal — запасной.
CLIENT_SIDE = {"network", "internal"}
# Запас: TMA-эндпоинты пока не ходят на ноду (Фаза 6 — уведомления).
RESERVED = {"node_unavailable"}


def frontend_codes() -> set[str]:
    if not ERRORS_TS.exists():
        pytest.skip("frontend/tma не найден рядом с backend/")
    match = re.search(r"API_ERROR_CODES\s*=\s*\[(.*?)\]\s*as const", ERRORS_TS.read_text(), re.S)
    assert match, "не нашёл API_ERROR_CODES в errors.ts"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def all_domain_codes() -> set[str]:
    found: set[str] = set()
    todo = [DomainError]
    while todo:
        cls = todo.pop()
        found.add(cls.code)
        todo.extend(cls.__subclasses__())
    return found


def test_the_parser_sees_the_codes() -> None:
    codes = frontend_codes()
    assert {"unauthorized", "initdata_expired", "rate_limited"} <= codes
    assert "network" in codes


def test_every_backend_code_is_either_known_to_the_frontend_or_explained() -> None:
    known = frontend_codes() | set(KNOWN_UNMAPPED) | ADMIN_ONLY
    unexplained = all_domain_codes() - known
    assert not unexplained, (
        f"новые коды ошибок {sorted(unexplained)}: добавьте во фронтенд (errors.ts, i18n) "
        "или объясните в KNOWN_UNMAPPED / ADMIN_ONLY"
    )


def test_the_frontend_expects_no_code_the_backend_never_sends() -> None:
    dead = frontend_codes() - all_domain_codes() - CLIENT_SIDE
    assert not dead, f"фронтенд ждёт коды, которых нет в бэкенде: {sorted(dead)}"


async def test_the_public_api_exposes_the_nine_contract_operations_and_the_download(
    public_client: AsyncClient,
) -> None:
    schema = (await public_client.get("/api/openapi.json")).json()
    operations = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        if path.startswith("/api/tma")
        for method in item
    }
    assert operations == {
        ("GET", "/api/tma/me"),
        ("GET", "/api/tma/plans"),
        ("GET", "/api/tma/subscription"),
        ("POST", "/api/tma/subscription/trial"),
        ("POST", "/api/tma/checkout"),
        ("GET", "/api/tma/devices"),
        ("POST", "/api/tma/devices"),
        ("DELETE", "/api/tma/devices/{device_id}"),
        ("GET", "/api/tma/connection"),
        ("GET", "/api/tma/download/{token}"),
    }
    names = set(schema["components"]["schemas"])
    # По этим именам frontend сверяет свои типы со схемой (Задача 20 плана TMA).
    assert {
        "MeOut",
        "PlanOut",
        "SubscriptionOut",
        "SubscriptionEnvelope",
        "DeviceOut",
        "CreateDeviceIn",
        "IssuedDeviceOut",
        "ConnectionOut",
        "CheckoutIn",
        "CheckoutOut",
    } <= names


async def test_every_error_the_tma_endpoints_produce_is_a_code_the_frontend_knows(
    public_client: AsyncClient,
    tma_client: AsyncClient,
    tma_headers: TmaHeaders,
    trial_plan: Plan,
) -> None:
    """Батарея заведомо неудачных запросов: ни один ответ об ошибке не должен стать `internal`."""
    allowed = frontend_codes() | set(KNOWN_UNMAPPED)
    seen: set[str] = set()

    async def expect_error(response_awaitable: object) -> None:
        r = await response_awaitable  # type: ignore[misc]
        assert r.status_code >= 400, r.request.url
        code = r.json()["error"]["code"]
        seen.add(code)
        assert code in allowed, f"{r.request.method} {r.request.url.path}: {code}"
        assert code != "internal", f"{r.request.method} {r.request.url.path}"

    bad = {"Authorization": "tma garbage"}
    old = tma_headers(age_s=10 * 86400)
    await expect_error(public_client.get("/api/tma/me"))
    await expect_error(public_client.get("/api/tma/me", headers=bad))
    await expect_error(public_client.get("/api/tma/me", headers=old))
    await expect_error(public_client.get("/api/tma/nope"))
    await expect_error(public_client.put("/api/tma/me"))
    await expect_error(public_client.get("/api/tma/download/" + "x" * 5000))
    await expect_error(tma_client.delete("/api/tma/devices/abc"))
    await expect_error(tma_client.delete("/api/tma/devices/999999"))
    await expect_error(tma_client.post("/api/tma/devices", json={"name": "a", "platform": "ios"}))
    await expect_error(tma_client.post("/api/tma/devices", json={"name": "", "platform": "ios"}))
    assert (await tma_client.post("/api/tma/subscription/trial")).status_code == 200
    await expect_error(tma_client.post("/api/tma/subscription/trial"))
    for _ in range(4):
        await tma_client.post("/api/tma/subscription/trial")
    await expect_error(tma_client.post("/api/tma/subscription/trial"))
    issued = await tma_client.post("/api/tma/devices", json={"name": "a", "platform": "ios"})
    assert issued.status_code == 200
    await expect_error(tma_client.post("/api/tma/devices", json={"name": "b", "platform": "ios"}))

    assert {
        "unauthorized",
        "initdata_expired",
        "not_found",
        "validation_error",
        "subscription_inactive",
        "trial_already_used",
        "rate_limited",
        "device_limit_reached",
    } <= seen
