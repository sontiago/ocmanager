"""Значения, секреты и файл `.env`. Формат `.env` задаёт `deploy/.env.example`: установщик
подставляет значения в него, а не держит свою копию, поэтому ключи не расходятся."""

import os
import re
import secrets
from pathlib import Path

DOMAIN_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BOT_TOKEN = re.compile(r"^\d{6,}:[\w-]{20,}$")
ADMIN_USER = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD, MAX_PASSWORD_BYTES = 12, 72


def normalize_domain(raw: str) -> str:
    """Домен из того, что обычно вставляют: с `https://`, слэшем, точкой, в любом регистре."""
    text = raw.strip().lower()
    for scheme in ("https://", "http://"):
        text = text.removeprefix(scheme)
    text = text.split("/", 1)[0].rstrip(".")
    if not text:
        raise ValueError("Введите доменное имя, например app.example.com.")
    if ":" in text:
        raise ValueError("Порт в адресе не нужен: Caddy работает на стандартных 80 и 443.")
    if re.fullmatch(r"[\d.]+", text):
        raise ValueError("Нужно имя домена, а не IP-адрес: Let's Encrypt выдаёт сертификат на имя.")
    labels = text.split(".")
    if len(labels) < 2:
        raise ValueError("Нужен полный домен вида app.example.com.")
    if any(not DOMAIN_LABEL.match(label) for label in labels):
        raise ValueError("В имени допустимы латинские буквы, цифры, дефис и точки.")
    return text


def validate_distinct_domains(app: str, vpn: str) -> None:
    if app == vpn:
        raise ValueError("Домены Mini App и VPN должны быть разными.")


def validate_email(raw: str) -> str:
    text = raw.strip()
    if not EMAIL.match(text):
        raise ValueError("Введите адрес почты, например admin@example.com.")
    return text


def validate_bot_token(raw: str) -> str:
    text = raw.strip()
    if not BOT_TOKEN.match(text):
        raise ValueError("Токен выглядит так: 123456789:AA… (его выдаёт @BotFather).")
    return text


def validate_admin_username(raw: str) -> str:
    text = raw.strip()
    if not ADMIN_USER.match(text):
        raise ValueError("Логин: 3–32 символа, строчные латинские буквы, цифры, «_», «.», «-».")
    return text


def validate_admin_password(raw: str) -> str:
    if len(raw) < MIN_PASSWORD:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD} символов.")
    if len(raw.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Пароль не должен быть длиннее {MAX_PASSWORD_BYTES} байт.")
    return raw


def generate_password() -> str:
    return secrets.token_urlsafe(18)  # 24 символа


def generate_secrets() -> dict[str, str]:
    return {
        # Только hex: пароли идут в URL подключения.
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "REDIS_PASSWORD": secrets.token_hex(24),
        "OCM_SECRET_KEY": secrets.token_urlsafe(48),
        "OCM_INTERNAL_TOKEN": secrets.token_urlsafe(48),
        "OCM_CAMOUFLAGE_SECRET": secrets.token_urlsafe(18),
    }


_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _ASSIGN.match(line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def render_env(values: dict[str, str], example: Path) -> str:
    """Шаблон с подставленными значениями. Ключ, которого нет в шаблоне, — ошибка: иначе
    опечатка в имени тихо давала бы пустую настройку."""
    template = example.read_text()
    known = set(parse_env(template))
    unknown = sorted(set(values) - known)
    if unknown:
        raise KeyError(f"ключи нет в {example.name}: {', '.join(unknown)}")
    lines = []
    for line in template.splitlines():
        match = _ASSIGN.match(line)
        if match and match.group(1) in values:
            lines.append(f"{match.group(1)}={values[match.group(1)]}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def write_private(path: Path, text: str) -> None:
    """Файл с секретами: права 0600 с момента создания (не chmod после записи) и принудительно
    для уже существующего файла — через дескриптор, чтобы не было окна между созданием и ужатием."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)


def write_env(path: Path, text: str) -> None:
    """Атомарная запись с правами 0600. Прежний файл сначала копируется в `.env.bak`, а в
    своё место новый встаёт одним `os.replace`: обрыв посередине оставляет старый `.env`."""
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        write_private(tmp, text)
        if path.exists():
            write_private(path.with_name(f"{path.name}.bak"), path.read_text())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
