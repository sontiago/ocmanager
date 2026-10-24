"""Файлы состояния ноды: allowed.list и crl.pem.

Оба файла ocserv читает сам и в любой момент (CRL — сразу при изменении,
без reload), поэтому запись только атомарная: временный файл в том же
каталоге + os.replace. Полузаписанного файла ocserv не увидит никогда.
"""

import ipaddress
import os
import re
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from cryptography import x509

from ocmanager.core.routes import normalize_routes

# Копия provisioning.pki.certs.USERNAME_RE: nodes не импортирует provisioning
# (граница модулей). Совпадение проверяет scripts/test_consistency.py.
USERNAME_RE: Final = re.compile(r"^c[1-9]\d{0,9}-d[1-9]\d{0,4}$")


def validate_username(username: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(f"invalid ocserv username {username!r}")
    return username


def render_allowlist(usernames: Iterable[str]) -> bytes:
    """Отсортированный список без повторов, по строке на username.
    Невалидный username — ValueError до какой-либо записи."""
    unique = sorted({validate_username(u) for u in usernames})
    return "".join(f"{u}\n" for u in unique).encode()


def parse_allowlist(data: bytes) -> set[str]:
    """Как есть, без валидации: reconcile должен видеть и мусор, чтобы его убрать."""
    return {line.strip() for line in data.decode(errors="replace").splitlines() if line.strip()}


ROUTES_HEADER = "# Управляется из админки ocmanager: правки руками будут перезаписаны.\n"
ROUTE_PREFIX = "no-route = "


def render_routes(routes: Iterable[str]) -> bytes:
    """Файл `default-user-config` для ocserv: по строке `no-route` на подсеть. Невалидный адрес —
    ValueError до записи; пустой список даёт файл только с комментарием."""
    lines = "".join(f"{ROUTE_PREFIX}{r}\n" for r in normalize_routes(list(routes)))
    return (ROUTES_HEADER + lines).encode()


def _route_order(route: str) -> tuple[int, int, str]:
    """По адресу, а не по строке; мусор — в конец."""
    try:
        net = ipaddress.IPv4Network(route, strict=False)
    except ValueError:
        return (1, 0, route)
    return (0, int(net.network_address), route)


def parse_routes(data: bytes) -> list[str]:
    """Что реально лежит в файле: нужны только строки `no-route`, остальное reconcile не волнует."""
    out = [
        line.strip().removeprefix(ROUTE_PREFIX.strip()).lstrip(" =").strip()
        for line in data.decode(errors="replace").splitlines()
        if line.strip().startswith("no-route")
    ]
    return sorted(out, key=_route_order)


def validate_crl(pem: bytes) -> None:
    try:
        x509.load_pem_x509_crl(pem)
    except ValueError:
        raise ValueError("not a PEM-encoded CRL") from None


def atomic_write(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)  # umask мог срезать биты
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)  # переименование переживёт падение питания
    finally:
        os.close(dir_fd)
