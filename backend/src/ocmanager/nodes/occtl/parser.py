"""Разбор JSON-вывода `occtl -j` (решение №11).

Ключи зафиксированы по фикстурам живого ocserv (fixtures/README.md), а не
угаданы. Разбор строгий: нет обязательного ключа или счётчик не число —
OcctlParseError с именем ключа, чтобы при обновлении ocserv сразу было видно,
что поменялось.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class OcctlParseError(Exception):
    pass


@dataclass(frozen=True)
class OcSession:
    session_id: str  # occtl "ID": уникален в пределах жизни процесса ocserv
    username: str
    remote_ip: str
    vpn_ip: str | None
    bytes_in: int  # RX сервера = upload клиента
    bytes_out: int  # TX сервера = download клиента
    connected_at: datetime  # aware UTC
    user_agent: str | None


@dataclass(frozen=True)
class OcStatus:
    up: bool
    active_sessions: int
    uptime_s: int
    raw: Mapping[str, Any]  # для админки «как есть»


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise OcctlParseError(f"invalid json: {exc}") from None


def _str(obj: Mapping[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise OcctlParseError(f"{key!r}: expected non-empty string, got {value!r}")
    return value


def _optional_str(obj: Mapping[str, Any], key: str) -> str | None:
    value = obj.get(key)
    return value if isinstance(value, str) and value else None


def _int(obj: Mapping[str, Any], key: str) -> int:
    """Число или строка из цифр: RX/TX ocserv отдаёт строкой ("3180")."""
    value = obj.get(key)
    if isinstance(value, bool):
        raise OcctlParseError(f"{key!r}: expected integer, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise OcctlParseError(f"{key!r}: expected integer, got {value!r}")


def _session(obj: Any) -> OcSession:
    if not isinstance(obj, dict):
        raise OcctlParseError(f"user entry: expected object, got {type(obj).__name__}")
    return OcSession(
        session_id=str(_int(obj, "ID")),
        username=_str(obj, "Username"),
        remote_ip=_str(obj, "Remote IP"),
        vpn_ip=_optional_str(obj, "IPv4"),
        bytes_in=_int(obj, "RX"),
        bytes_out=_int(obj, "TX"),
        connected_at=datetime.fromtimestamp(_int(obj, "raw_connected_at"), tz=UTC),
        user_agent=_optional_str(obj, "User-Agent"),
    )


def parse_users(text: str) -> list[OcSession]:
    data = _load(text)
    if not isinstance(data, list):
        raise OcctlParseError(f"show users: expected array, got {type(data).__name__}")
    return [_session(item) for item in data]


def parse_status(text: str) -> OcStatus:
    data = _load(text)
    if not isinstance(data, dict):
        raise OcctlParseError(f"show status: expected object, got {type(data).__name__}")
    return OcStatus(
        up=_str(data, "Status") == "online",
        active_sessions=_int(data, "Active sessions"),
        uptime_s=_int(data, "uptime"),
        raw=data,
    )
