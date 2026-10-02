"""Клиент Telegram Bot API: одна функция — sendMessage."""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

import httpx

# httpx пишет каждый запрос в лог целиком (INFO), а токен бота лежит в URL запроса:
# /bot<token>/sendMessage. Уровень выставляется при импорте — любой процесс, который шлёт
# сообщения, получает его вместе с функцией.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = "https://api.telegram.org"
ERROR_LIMIT = 200


class SendOutcome(Enum):
    SENT = auto()
    RETRY = auto()
    UNDELIVERABLE = auto()  # получатель недоступен насовсем: повтор не поможет


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    retry_after: int | None = None
    error: str | None = None


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def send_message(
    http: httpx.AsyncClient, bot_token: str, chat_id: int, text: str
) -> SendResult:
    try:
        response = await http.post(
            f"{API_URL}/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": text}
        )
    except httpx.HTTPError as exc:
        # Текст исключения может содержать URL, а в нём — токен: сохраняем только тип.
        return SendResult(SendOutcome.RETRY, error=type(exc).__name__)
    if response.status_code == 200:
        return SendResult(SendOutcome.SENT)

    body = _body(response)
    description = str(body.get("description", ""))[:ERROR_LIMIT]
    error = f"{response.status_code}: {description}"
    if response.status_code == 429:
        parameters = body.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if isinstance(retry_after, int) and retry_after > 0:
            return SendResult(SendOutcome.RETRY, retry_after=retry_after, error=error)
    if response.status_code == 403 or (
        response.status_code == 400 and "chat not found" in description.lower()
    ):
        return SendResult(SendOutcome.UNDELIVERABLE, error=error)
    return SendResult(SendOutcome.RETRY, error=error)
