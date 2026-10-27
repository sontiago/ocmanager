"""Проверки сервера до установки. Функции чистые: принимают текст или число, а читает систему
`SystemInfo.read`, так что каждое правило проверяется таблицей случаев."""

import os
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from installer.i18n import _
from installer.runner import CommandError, Net, Runner

GIB = 1024**3
MIN_FREE_BYTES = 8 * GIB
SWAP_BELOW_BYTES = 2 * GIB
PORTS = (("80", "tcp"), ("443", "tcp"), ("443", "udp"))


def _supported() -> str:
    return _("Debian 12+ или Ubuntu 22.04+")


class Finding(NamedTuple):
    ok: bool
    title: str
    hint: str
    blocking: bool
    code: str


def ok(title: str, code: str) -> Finding:
    return Finding(True, title, "", False, code)


def blockers(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if not f.ok and f.blocking]


def _os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:2])


def check_os(os_release_text: str) -> Finding:
    info = _os_release(os_release_text)
    distro, version = info.get("ID", ""), _version(info.get("VERSION_ID", ""))
    supported = (distro == "debian" and version >= (12,)) or (
        distro == "ubuntu" and version >= (22, 4)
    )
    title = _("Операционная система поддерживается")
    if supported:
        return ok(title, "os_ok")
    name = info.get("PRETTY_NAME") or distro or _("неизвестная система")
    return Finding(
        False,
        title,
        _("Здесь {name}. Установщик рассчитан на {supported}.", name=name, supported=_supported()),
        True,
        "os_unsupported",
    )


def check_root(euid: int) -> Finding:
    title = _("Запущено от root")
    if euid == 0:
        return ok(title, "root_ok")
    return Finding(False, title, _("Запустите через sudo: sudo ./install.sh"), True, "not_root")


def check_python(version: tuple[int, ...]) -> Finding:
    title = _("Python 3.10 или новее")
    if version[:2] >= (3, 10):
        return ok(title, "python_ok")
    return Finding(False, title, _("Установите python3 версии 3.10 или новее."), True, "python_old")


def _meminfo_bytes(text: str, key: str) -> int:
    match = re.search(rf"^{key}:\s+(\d+)\s*kB", text, re.M)
    return int(match.group(1)) * 1024 if match else 0


def needs_swap(meminfo: str) -> bool:
    """Меньше 2 ГБ памяти и нет swap: сборка образов на таком сервере падает по OOM."""
    return _meminfo_bytes(meminfo, "MemTotal") < SWAP_BELOW_BYTES and (
        _meminfo_bytes(meminfo, "SwapTotal") == 0
    )


def check_memory(meminfo: str) -> Finding:
    title = _("Достаточно памяти для сборки")
    if not needs_swap(meminfo):
        return ok(title, "memory_ok")
    return Finding(
        False,
        title,
        _(
            "Памяти меньше 2 ГБ и нет swap: сборка образов может упасть. "
            "Мастер предложит создать swap 2 ГБ."
        ),
        False,
        "swap_needed",
    )


def check_disk(free_bytes: int) -> Finding:
    title = _("Достаточно места на диске")
    if free_bytes >= MIN_FREE_BYTES:
        return ok(title, "disk_ok")
    free_gb = free_bytes / GIB
    return Finding(
        False,
        title,
        _(
            "Свободно {free_gb} ГБ, нужно не меньше 8 ГБ (образы, базы, резервные копии).",
            free_gb=f"{free_gb:.1f}",
        ),
        True,
        "disk_low",
    )


def _listeners(output: str, port: str) -> list[str]:
    """Процессы, слушающие порт; пустая строка в списке — процесс не определён."""
    found: list[str] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        if fields[3].rsplit(":", 1)[-1] != port:
            continue
        match = re.search(r'users:\(\("([^"]+)"', line)
        found.append(match.group(1) if match else "")
    return found


def check_ports(runner: Runner, *, our_containers_running: bool = False) -> list[Finding]:
    """80/tcp, 443/tcp и 443/udp свободны. Если стек уже стоит (повторный запуск), порты держат
    наши же контейнеры — это не конфликт."""
    outputs: dict[str, str] = {}
    for proto, flags in (("tcp", "-H -ltnp"), ("udp", "-H -lunp")):
        try:
            result = runner.run(["ss", *flags.split()], check=False)
        except CommandError:
            result = None
        if result is None or result.code != 0:
            return [
                Finding(
                    False,
                    _("Проверка занятых портов"),
                    _(
                        "Не удалось выполнить ss (пакет iproute2). Убедитесь сами, что порты "
                        "80/tcp, 443/tcp и 443/udp свободны."
                    ),
                    False,
                    "ports_unchecked",
                )
            ]
        outputs[proto] = result.stdout
    findings: list[Finding] = []
    for port, proto in PORTS:
        title = _("Порт {port}/{proto} свободен", port=port, proto=proto)
        owners = _listeners(outputs[proto], port)
        if not owners or our_containers_running:
            findings.append(ok(title, f"port_{port}_{proto}_ok"))
            continue
        who = next((name for name in owners if name), _("неизвестный процесс"))
        findings.append(
            Finding(
                False,
                _("Порт {port}/{proto} занят", port=port, proto=proto),
                _("Его держит {who}. Остановите его: Caddy должен занять 80 и 443.", who=who),
                True,
                f"port_{port}_{proto}_busy",
            )
        )
    return findings


def check_docker(runner: Runner) -> Finding:
    server = runner.run(["docker", "version", "--format", "{{.Server.Version}}"], check=False)
    if server.code != 0:
        missing = server.code == 127 or "not found" in server.stderr
        if missing:
            return Finding(
                False,
                _("Docker установлен"),
                _(
                    "Docker не найден. Мастер может установить его (docker.io и docker-compose-v2 "
                    "из репозитория дистрибутива) — он спросит разрешения."
                ),
                False,
                "docker_missing",
            )
        return Finding(
            False,
            _("Docker запущен"),
            _("Docker установлен, но не отвечает. Запустите его: sudo systemctl start docker"),
            True,
            "docker_down",
        )
    major = _version(server.stdout.strip() or "0")[:1]
    if major < (24,):
        return Finding(
            False,
            _("Docker 24 или новее"),
            _(
                "Установлен Docker {version}, нужен 24+. Обновите пакеты docker.",
                version=server.stdout.strip(),
            ),
            True,
            "docker_old",
        )
    compose = runner.run(["docker", "compose", "version", "--short"], check=False)
    if compose.code != 0:
        return Finding(
            False,
            _("Docker Compose v2"),
            _(
                "Нужен Compose v2 (команда «docker compose»). "
                "На Ubuntu: apt-get install docker-compose-v2"
            ),
            True,
            "compose_missing",
        )
    return ok(_("Docker и Compose v2 установлены"), "docker_ok")


def check_dns(net: Net, domain: str, public_ip: str | None) -> Finding:
    title = _("Домен {domain} указывает на этот сервер", domain=domain)
    records = net.resolve_a(domain)
    if not records:
        return Finding(
            False,
            title,
            _(
                "У {domain} нет A-записи. Создайте её у регистратора домена с адресом этого "
                "сервера и подождите несколько минут.",
                domain=domain,
            ),
            True,
            "dns_missing",
        )
    if public_ip is None:
        return Finding(
            False,
            title,
            _(
                "Не удалось определить внешний IP сервера. Убедитесь сами, что {domain} "
                "указывает на него (сейчас: {records}).",
                domain=domain,
                records=", ".join(records),
            ),
            False,
            "dns_unverified",
        )
    if public_ip in records:
        return ok(title, "dns_ok")
    return Finding(
        False,
        title,
        _(
            "{domain} указывает на {records}, а этот сервер — {ip}. "
            "Поправьте A-запись и подождите несколько минут.",
            domain=domain,
            records=", ".join(records),
            ip=public_ip,
        ),
        True,
        "dns_mismatch",
    )


@dataclass(frozen=True)
class SystemInfo:
    os_release: str
    euid: int
    python: tuple[int, ...]
    meminfo: str
    free_bytes: int

    @classmethod
    def read(cls, root: Path) -> "SystemInfo":
        def text(path: str) -> str:
            try:
                return Path(path).read_text()
            except OSError:
                return ""

        return cls(
            os_release=text("/etc/os-release"),
            euid=os.geteuid(),
            python=tuple(sys.version_info[:3]),
            meminfo=text("/proc/meminfo"),
            free_bytes=shutil.disk_usage(root).free,
        )


def run_all(
    runner: Runner,
    net: Net,
    system: SystemInfo,
    *,
    domains: Sequence[str] = (),
    our_containers_running: bool = False,
) -> list[Finding]:
    """Все проверки в порядке показа. Домены проверяются, только если уже известны."""
    findings = [
        check_os(system.os_release),
        check_root(system.euid),
        check_python(system.python),
        check_memory(system.meminfo),
        check_disk(system.free_bytes),
        check_docker(runner),
        *check_ports(runner, our_containers_running=our_containers_running),
    ]
    if domains:
        public_ip = net.public_ip()
        findings.extend(check_dns(net, domain, public_ip) for domain in domains)
    return findings
