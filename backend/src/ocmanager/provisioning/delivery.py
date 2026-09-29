"""Одноразовая выдача .p12. Файл не пишется на диск (Global Constraints): между
выпуском и скачиванием он живёт в Redis зашифрованным, 15 минут (решение №7)."""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis

LINK_TTL_S: Final = 900


@dataclass(frozen=True)
class DeliveryTicket:
    token: str
    expires_at: datetime


def _key(token: str) -> str:
    # В Redis лежит только хеш токена: дамп Redis не даёт рабочих ссылок.
    return f"p12:{hashlib.sha256(token.encode()).hexdigest()}"


async def put_p12(
    redis: Redis, fernet: Fernet, p12: bytes, *, filename: str, now: datetime
) -> DeliveryTicket:
    token = secrets.token_urlsafe(32)
    blob = json.dumps({"filename": filename, "data_b64": base64.b64encode(p12).decode()})
    stored = await redis.set(_key(token), fernet.encrypt(blob.encode()), ex=LINK_TTL_S, nx=True)
    if not stored:  # 256 бит случайности: коллизия означает сбой генератора, а не невезение
        raise RuntimeError("p12 delivery token collision")
    return DeliveryTicket(token=token, expires_at=now + timedelta(seconds=LINK_TTL_S))


async def take_p12(redis: Redis, fernet: Fernet, token: str) -> tuple[str, bytes] | None:
    """GETDEL: второй запрос с тем же токеном получает None. Испорченное значение — тоже None."""
    raw = await redis.getdel(_key(token))
    if raw is None:
        return None
    try:
        data = json.loads(fernet.decrypt(raw))
        return str(data["filename"]), base64.b64decode(data["data_b64"])
    except (InvalidToken, ValueError, KeyError):
        return None
