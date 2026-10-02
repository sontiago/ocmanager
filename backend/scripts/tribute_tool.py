"""Инструменты Задачи 5.8 (живой Tribute): отправить подписанный вебхук, выгрузить снятое
тело из БД, показать, как разобран payload и какие гипотезы маппинга не подтвердились.

    uv run python scripts/tribute_tool.py list
    uv run python scripts/tribute_tool.py dump 3 /tmp/new_subscription.json
    uv run python scripts/tribute_tool.py inspect /tmp/new_subscription.json
    uv run python scripts/tribute_tool.py send new_subscription          # фикстура по имени
    uv run python scripts/tribute_tool.py send /tmp/body.json --url https://<туннель>/webhooks/tribute

Ключ для `send` — OCM_TRIBUTE_API_KEY из окружения или backend/.env.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from ocmanager.billing.providers.base import ProviderPayloadError
from ocmanager.billing.providers.tribute import SIGNATURE_HEADER, TributeProvider
from ocmanager.billing.testing import FIXTURES, sign
from ocmanager.core.config import get_settings
from ocmanager.core.db import make_engine

DEFAULT_URL = "http://localhost:8000/webhooks/tribute"
HINT_WORDS = ("id", "uuid", "uid", "key")


def load_body(target: str) -> bytes:
    """Файл по пути или фикстура по имени (`new_subscription`)."""
    path = Path(target)
    if path.is_file():
        return path.read_bytes()
    fixture = FIXTURES / f"{target}.json"
    if fixture.is_file():
        return fixture.read_bytes()
    raise SystemExit(f"нет ни файла, ни фикстуры: {target}")


def inspect_body(body: bytes) -> list[str]:
    """Отчёт: как разобран payload и что не сошлось с гипотезами (см. README фикстур)."""
    lines: list[str] = []
    try:
        data = json.loads(body)
    except ValueError as exc:
        return [f"НЕ JSON: {exc}"]
    if not isinstance(data, dict):
        return [f"JSON, но не объект: {type(data).__name__}"]

    inner = data.get("payload")
    lines.append(f"верхний уровень: {sorted(data)}")
    lines.append(f"payload: {sorted(inner) if isinstance(inner, Mapping) else repr(inner)}")
    try:
        event = TributeProvider("inspect").parse(data)
    except ProviderPayloadError as exc:
        return [*lines, f"РАЗБОР УПАЛ: {exc}"]

    lines.append(f"имя события: {event.raw_name!r} → {event.kind}")
    if event.kind == "ignored":
        lines.append("  ! событие не входит в таблицу _KINDS (billing/providers/tribute.py)")
        return lines
    resolved = {
        "telegram_id": event.telegram_id,
        "external_payment_id": event.external_payment_id,
        "product_ref": event.product_ref,
        "amount": event.amount,
        "currency": event.currency,
    }
    for name, value in resolved.items():
        mark = "  ! НЕ НАЙДЕНО" if value is None else ""
        lines.append(f"  {name} = {value!r}{mark}")
    if isinstance(inner, Mapping):
        lines.append(
            f"  в теле: price={inner.get('price')!r} (платит клиент → выручка), "
            f"amount={inner.get('amount')!r} (после комиссии), period_id={inner.get('period_id')!r}"
        )
        used = {"telegram_user_id", "subscription_id", "period_id", "expires_at", "price"}
        used |= {"amount", "currency", "purchase_id"}
        spare = [k for k in inner if k not in used and any(w in k.lower() for w in HINT_WORDS)]
        if spare:
            lines.append(f"  поля-идентификаторы, которые разбор не использует: {spare}")
    own_ids = [k for k in data if k != "payload" and any(w in k.lower() for w in HINT_WORDS)]
    if own_ids:
        lines.append(
            f"  ! у вебхука может быть собственный id: {own_ids} (event_id сейчас — sha256)"
        )
    return lines


def cmd_inspect(args: argparse.Namespace) -> int:
    print("\n".join(inspect_body(load_body(args.target))))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    secret = get_settings().tribute_api_key
    key = args.key or (secret.get_secret_value() if secret else "")
    if not key:
        raise SystemExit("нет ключа: задайте OCM_TRIBUTE_API_KEY или --key")
    body = load_body(args.target)
    response = httpx.post(
        args.url, content=body, headers={SIGNATURE_HEADER: sign(body, key)}, timeout=10
    )
    print(response.status_code, response.text)
    return 0 if response.status_code == 200 else 1


async def _fetch(sql: str, params: dict[str, Any]) -> Sequence[Any]:
    engine = make_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).all()
    finally:
        await engine.dispose()


def cmd_list(_: argparse.Namespace) -> int:
    rows = asyncio.run(
        _fetch(
            "SELECT id, status, attempts, signature_ok, payload->>'name', left(last_error, 70)"
            " FROM webhook_events ORDER BY id",
            {},
        )
    )
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    rows = asyncio.run(
        _fetch("SELECT raw_body FROM webhook_events WHERE id = :id", {"id": args.event_id})
    )
    if not rows:
        raise SystemExit(f"вебхука {args.event_id} нет")
    Path(args.out).write_bytes(bytes(rows[0][0]))
    print(f"записано {args.out} (тело как пришло; персональные данные замените вручную)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect", help="как разобран payload (файл или имя фикстуры)")
    p.add_argument("target")
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("send", help="отправить подписанный вебхук")
    p.add_argument("target")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--key", default=None)
    p.set_defaults(func=cmd_send)
    p = sub.add_parser("list", help="вебхуки в БД: id, статус, имя события")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("dump", help="записать сырое тело вебхука из БД в файл")
    p.add_argument("event_id", type=int)
    p.add_argument("out")
    p.set_defaults(func=cmd_dump)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
