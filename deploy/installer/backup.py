"""Резервные копии: один шифрованный файл с базой, удостоверяющим центром (CA) и `.env`.

Потеря тома `pki` — это потеря CA: все выданные клиентам ключи придётся перевыпускать. Поэтому
копия обязательно шифруется (в ней приватный ключ CA), а восстановление сначала полностью
проверяет файл и только потом останавливает сервисы."""

import json
import re
import secrets
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from installer.config import write_private
from installer.runner import CommandError, Runner

BACKUP_DIR = Path("/var/backups/ocmanager")
KEY_FILE = Path("/root/.ocmanager-backup-key")
KEEP = 14
KEEP_EMERGENCY = 3
FORMAT = 1
PKI_VOLUME = "ocmanager_pki"
DUMP_IN_CONTAINER = "/tmp/ocm.dump"  # noqa: S108 — путь внутри контейнера postgres
# Всё, кроме баз: их восстановление идёт под остановленным приложением.
APP_SERVICES = (
    "api-public",
    "api-admin",
    "worker",
    "bot",
    "ocserv",
    "caddy",
    "nginx",
    "docker-proxy",
)
MEMBERS = frozenset({"db.dump", "pki.tgz", "env", "manifest.json"})
REMOTE = re.compile(r"^[^/\s]+@[^/\s:]+:.+$")
MARKER = "last-ok"
PREFIX, EMERGENCY_PREFIX = "ocmanager", "pre-restore"


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class BackupPaths:
    root: Path
    backup_dir: Path = BACKUP_DIR
    key_file: Path = KEY_FILE

    @property
    def deploy(self) -> Path:
        return self.root / "deploy"


@dataclass(frozen=True)
class Manifest:
    created: str
    version: str
    format: int


def validate_remote(raw: str) -> str:
    """Пусто — не копировать; `user@host:/путь` или абсолютный путь (смонтированный диск)."""
    value = raw.strip()
    if value and not REMOTE.match(value) and not value.startswith("/"):
        raise ValueError("Ожидается пользователь@сервер:/путь или абсолютный путь к каталогу.")
    return value


def name_for(now: datetime, prefix: str = PREFIX) -> str:
    return f"{prefix}-{now:%Y-%m-%d-%H%M}.tar.gz.enc"


def ensure_key(path: Path) -> str:
    """Ключ шифрования копий. Создаётся один раз; существующий не трогаем."""
    if path.exists():
        return read_key(path)
    key = secrets.token_urlsafe(32)
    write_private(path, key + "\n")
    return key


def read_key(path: Path) -> str:
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise BackupError(f"нет файла ключа {path}: {exc}") from exc
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise BackupError(f"права на файл ключа {path} слишком открытые: chmod 600 {path}")
    return path.read_text().strip()


def _compose(paths: BackupPaths, runner: Runner, *args: str, check: bool = True) -> None:
    runner.run(["docker", "compose", *args], cwd=paths.deploy, check=check)


def _openssl(runner: Runner, key_file: Path, src: Path, dst: Path, *, decrypt: bool) -> None:
    cmd = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt"]
    if decrypt:
        cmd.append("-d")
    runner.run([*cmd, "-in", str(src), "-out", str(dst), "-pass", f"file:{key_file}"])


def create(paths: BackupPaths, runner: Runner, now: datetime, *, prefix: str = PREFIX) -> Path:
    """Снимает копию. Промежуточные файлы лежат в закрытом каталоге и удаляются при любом
    исходе; существующие копии не трогаются."""
    read_key(paths.key_file)  # неверные права ключа — отказ до всякой работы
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    paths.backup_dir.chmod(0o700)
    work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=paths.backup_dir))
    try:
        try:
            _compose(
                paths, runner, "exec", "-T", "postgres",
                "pg_dump", "-U", "ocm", "-Fc", "-f", DUMP_IN_CONTAINER, "ocmanager",
            )  # fmt: skip
            try:
                _compose(
                    paths, runner, "cp", f"postgres:{DUMP_IN_CONTAINER}", str(work / "db.dump")
                )
            finally:
                _compose(
                    paths,
                    runner,
                    "exec",
                    "-T",
                    "postgres",
                    "rm",
                    "-f",
                    DUMP_IN_CONTAINER,
                    check=False,
                )
            runner.run([
                "docker", "run", "--rm",
                "-v", f"{PKI_VOLUME}:/pki:ro", "-v", f"{work}:/out",
                "alpine", "tar", "czf", "/out/pki.tgz", "-C", "/pki", ".",
            ])  # fmt: skip
            write_private(work / "env", (paths.deploy / ".env").read_text())
            revision = runner.run(["git", "rev-parse", "HEAD"], cwd=paths.root, check=False)
            manifest = {
                "created": now.isoformat(),
                "version": revision.stdout.strip()[:12] or "unknown",
                "format": FORMAT,
            }
            (work / "manifest.json").write_text(json.dumps(manifest))
            bundle = work / "bundle.tar.gz"
            with tarfile.open(bundle, "w:gz") as tar:
                for member in sorted(MEMBERS):
                    tar.add(work / member, arcname=member)
            encrypted = work / "out.enc"
            _openssl(runner, paths.key_file, bundle, encrypted, decrypt=False)
        except (CommandError, OSError) as exc:
            raise BackupError(f"резервная копия не создана: {exc}") from exc
        final = paths.backup_dir / name_for(now, prefix)
        encrypted.chmod(0o600)
        encrypted.replace(final)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)


def extract(path: Path, key_file: Path, runner: Runner, dest: Path) -> Manifest:
    """Расшифровывает и раскладывает копию в `dest`. Принимает только четыре известных файла и
    не доверяет именам из архива: путь наружу из каталога невозможен."""
    read_key(key_file)
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    bundle = dest / ".bundle.tar.gz"
    try:
        try:
            _openssl(runner, key_file, path, bundle, decrypt=True)
        except CommandError as exc:
            raise BackupError(
                "не удалось расшифровать копию: неверный ключ или файл повреждён"
            ) from exc
        try:
            with tarfile.open(bundle, "r:gz") as tar:
                members = tar.getmembers()
                bad = [m.name for m in members if m.name not in MEMBERS or not m.isfile()]
                if bad:
                    raise BackupError(f"в архиве недопустимые файлы: {', '.join(bad)}")
                for member in members:
                    source = tar.extractfile(member)
                    assert source is not None
                    with (dest / member.name).open("wb") as out:
                        shutil.copyfileobj(source, out)
                    (dest / member.name).chmod(0o600)
        except tarfile.TarError as exc:
            raise BackupError("копия повреждена: архив не читается") from exc
    finally:
        bundle.unlink(missing_ok=True)
    try:
        manifest = json.loads((dest / "manifest.json").read_text())
        parsed = Manifest(
            created=str(manifest["created"]),
            version=str(manifest["version"]),
            format=int(manifest["format"]),
        )
    except (OSError, ValueError, KeyError) as exc:
        raise BackupError("в копии нет читаемого manifest.json") from exc
    missing = MEMBERS - {p.name for p in dest.iterdir()}
    if missing:
        raise BackupError(f"в копии нет файлов: {', '.join(sorted(missing))}")
    if parsed.format != FORMAT:
        raise BackupError(f"неизвестный формат копии: {parsed.format}")
    return parsed


def verify(path: Path, key_file: Path, runner: Runner) -> Manifest:
    work = Path(tempfile.mkdtemp(prefix=".verify-"))
    try:
        return extract(path, key_file, runner, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restore(
    path: Path,
    paths: BackupPaths,
    runner: Runner,
    now: datetime,
    *,
    restore_env: bool = False,
    emergency: bool = True,
) -> Manifest:
    """Возвращает базу и CA из копии. Порядок: проверить файл → аварийная копия текущего
    состояния → остановить приложение → база → CA → (по желанию) `.env` → запуск."""
    work = Path(tempfile.mkdtemp(prefix=".restore-"))
    try:
        manifest = extract(path, paths.key_file, runner, work)  # до любых изменений
        saved: Path | None = None
        if emergency:
            try:
                saved = create(paths, runner, now, prefix=EMERGENCY_PREFIX)
            except BackupError as exc:
                raise BackupError(
                    f"{exc}. Если база сейчас недоступна и терять нечего, "
                    "повторите с --no-emergency."
                ) from exc
        try:
            _compose(paths, runner, "stop", *APP_SERVICES)
            psql = ["exec", "-T", "postgres", "psql", "-U", "ocm", "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-c"]  # fmt: skip
            _compose(paths, runner, *psql, "DROP DATABASE IF EXISTS ocmanager WITH (FORCE)")
            _compose(paths, runner, *psql, "CREATE DATABASE ocmanager OWNER ocm")
            _compose(paths, runner, "cp", str(work / "db.dump"), f"postgres:{DUMP_IN_CONTAINER}")
            _compose(
                paths, runner, "exec", "-T", "postgres",
                "pg_restore", "-U", "ocm", "-d", "ocmanager", "--no-owner", "--exit-on-error",
                DUMP_IN_CONTAINER,
            )  # fmt: skip
            _compose(
                paths, runner, "exec", "-T", "postgres", "rm", "-f", DUMP_IN_CONTAINER, check=False
            )
            runner.run([
                "docker", "run", "--rm",
                "-v", f"{PKI_VOLUME}:/pki", "-v", f"{work}:/in:ro",
                "alpine", "sh", "-c", "rm -rf /pki/* /pki/.[!.]* ; tar xzf /in/pki.tgz -C /pki",
            ])  # fmt: skip
            if restore_env:
                env = paths.deploy / ".env"
                if env.exists():
                    write_private(paths.deploy / ".env.pre-restore", env.read_text())
                write_private(env, (work / "env").read_text())
            _compose(paths, runner, "up", "-d")
        except (CommandError, OSError) as exc:
            hint = f" Аварийная копия до восстановления: {saved}." if saved else ""
            raise BackupError(
                f"восстановление прервано: {exc}.{hint} Сервисы могут быть остановлены: "
                "повторите «ocm restore» или запустите «docker compose up -d»."
            ) from exc
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _sorted_copies(directory: Path, prefix: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(f"{prefix}-*.tar.gz.enc"))


def prune(directory: Path, keep: int = KEEP) -> list[Path]:
    """Оставляет `keep` последних обычных копий и `KEEP_EMERGENCY` аварийных."""
    removed: list[Path] = []
    for prefix, limit in ((PREFIX, keep), (EMERGENCY_PREFIX, KEEP_EMERGENCY)):
        copies = _sorted_copies(directory, prefix)
        for old in copies[: max(0, len(copies) - limit)]:
            old.unlink()
            removed.append(old)
    return removed


def record_success(directory: Path, now: datetime) -> None:
    write_private(directory / MARKER, now.isoformat() + "\n")


def age_hours(directory: Path, now: datetime) -> float | None:
    """Сколько часов назад была последняя успешная копия; None — не знаем."""
    try:
        stamp = datetime.fromisoformat((directory / MARKER).read_text().strip())
    except (OSError, ValueError):
        return None
    return (now - stamp).total_seconds() / 3600


def copy_offsite(file: Path, target: str, runner: Runner) -> None:
    """Копия на другой сервер (`user@host:/путь`, по ключу SSH) или в локальный каталог."""
    if REMOTE.match(target):
        ssh = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
        cmd = ["rsync", "-a", "-e", ssh, str(file), target]
    else:
        cmd = ["cp", "-p", str(file), target]
    try:
        runner.run(cmd)
    except CommandError as exc:
        raise BackupError(f"копия не отправлена в {target}: {exc}") from exc
