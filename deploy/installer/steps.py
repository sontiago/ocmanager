"""Шаги установки и файл состояния. Порядок шагов — тот же, что в `deploy/README.md`: базы,
CA, администратор, остальное. Каждый шаг после успеха отмечается в `deploy/.install-state`,
поэтому повторный запуск продолжает с места сбоя и не трогает сделанное."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from installer import backup, i18n, systemd
from installer.config import render_env, write_env
from installer.i18n import _
from installer.runner import CommandError, Net, Result, Runner

CERT_TIMEOUT_S = 300
CERT_POLL_S = 10
SWAP_SIZE = "2G"
TLS_OK = "Verify return code: 0 (ok)"


class StepError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        self.message = message
        self.hint = hint
        super().__init__(f"{message}\n{hint}" if hint else message)


class State:
    """Какие шаги сделаны. Секретов здесь нет: только имена шагов и несекретные ответы."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data = self._load()

    def _load(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {"done": [], "answers": {}}
        if not isinstance(data, dict):
            return {"done": [], "answers": {}}
        return {"done": list(data.get("done", [])), "answers": dict(data.get("answers", {}))}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))
        tmp.replace(self.path)

    def done(self) -> list[str]:
        return list(self._data["done"])  # type: ignore[call-overload]

    def is_done(self, step: str) -> bool:
        return step in self.done()

    def mark(self, step: str) -> None:
        if not self.is_done(step):
            self._data["done"] = [*self.done(), step]
            self._save()

    def reset(self) -> None:
        self._data["done"] = []
        self._save()

    def answers(self) -> dict[str, str]:
        return dict(self._data["answers"])  # type: ignore[call-overload]

    def remember(self, **answers: str) -> None:
        self._data["answers"] = {**self.answers(), **answers}
        self._save()


@dataclass
class Context:
    runner: Runner
    net: Net
    root: Path
    values: dict[str, str]
    admin_user: str
    admin_password: str
    state: State
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    out: Callable[[str], None] = print
    warn: Callable[[str], None] = print
    dry_run: bool = False
    want_swap: bool = False
    want_docker: bool = False
    want_backup: bool = False
    reuse_env: bool = False
    swapfile: Path = Path("/swapfile")
    fstab: Path = Path("/etc/fstab")
    backup_dir: Path = backup.BACKUP_DIR
    key_file: Path = backup.KEY_FILE
    unit_dir: Path = systemd.UNIT_DIR
    ocm_link: Path = systemd.OCM_LINK
    notes: list[str] = field(default_factory=list)

    @property
    def deploy(self) -> Path:
        return self.root / "deploy"

    def compose(self, *args: str, input: str | None = None, check: bool = True) -> Result:
        return self.runner.run(
            ["docker", "compose", *args], cwd=self.deploy, input=input, check=check
        )


@dataclass(frozen=True)
class Step:
    name: str
    title: str
    run: Callable[[Context], bool]  # True — сделано (отметить), False — пропущено


def _env(ctx: Context) -> bool:
    if ctx.reuse_env:
        return True
    write_env(ctx.deploy / ".env", render_env(ctx.values, ctx.deploy / ".env.example"))
    return True


def _swap(ctx: Context) -> bool:
    if not ctx.want_swap:
        return False
    path = str(ctx.swapfile)
    if not ctx.swapfile.exists():
        ctx.runner.run(["fallocate", "-l", SWAP_SIZE, path])
        ctx.runner.run(["chmod", "600", path])
        ctx.runner.run(["mkswap", path])
        ctx.runner.run(["swapon", path])
    line = f"{path} none swap sw 0 0"
    current = ctx.fstab.read_text() if ctx.fstab.exists() else ""
    if line not in current.splitlines():
        ctx.fstab.write_text(
            current + ("" if current.endswith("\n") or not current else "\n") + line + "\n"
        )
    return True


def _docker(ctx: Context) -> bool:
    if not ctx.want_docker:
        return False
    env = {"DEBIAN_FRONTEND": "noninteractive"}
    ctx.runner.run(["apt-get", "update"], env=env)
    ctx.runner.run(["apt-get", "install", "-y", "docker.io", "docker-compose-v2"], env=env)
    ctx.runner.run(["systemctl", "enable", "--now", "docker"])
    return True


def _build(ctx: Context) -> bool:
    ctx.compose("build")
    return True


def _infra(ctx: Context) -> bool:
    ctx.compose("up", "-d", "postgres", "redis", "volume-init")
    return True


def _tolerate(ctx: Context, args: list[str], marker: str, *, input: str | None = None) -> bool:
    """Команда, которая при повторном запуске честно отвечает «уже есть»: это не ошибка."""
    result = ctx.compose(*args, input=input, check=False)
    if result.code != 0 and marker not in (result.stdout + result.stderr):
        raise CommandError(["docker", "compose", *args], result.code, result.stderr)
    return True


def _pki(ctx: Context) -> bool:
    return _tolerate(ctx, ["run", "--rm", "-T", "cli", "pki", "init"], "уже существует")


def _admin(ctx: Context) -> bool:
    return _tolerate(
        ctx,
        ["run", "--rm", "-T", "cli", "admin", "create", ctx.admin_user, "--password-stdin"],
        "already exists",
        input=ctx.admin_password + "\n",
    )


def _stack(ctx: Context) -> bool:
    ctx.compose("up", "-d")
    return True


def _certs(ctx: Context) -> bool:
    """Caddy выпускает оба сертификата сам; ждём, пока TLS-цепочка на обоих доменах станет
    валидной. Домены проверяются по очереди: так понятно, на каком именно застряли."""
    deadline = ctx.clock() + CERT_TIMEOUT_S
    for domain in (ctx.values["DOMAIN_APP"], ctx.values["DOMAIN_VPN"]):
        while not _tls_ready(ctx, domain):
            if ctx.clock() + CERT_POLL_S > deadline:
                raise StepError(
                    _(
                        "Сертификат для {domain} не выпущен за {minutes} минут.",
                        domain=domain,
                        minutes=CERT_TIMEOUT_S // 60,
                    ),
                    _(
                        "Проверьте, что A-запись {domain} указывает на этот сервер и порт 80 "
                        "открыт снаружи (в том числе в облачном firewall провайдера). "
                        "Что говорит Caddy: docker compose logs caddy. "
                        "Лимит Let's Encrypt — 5 неудач в час. После исправления запустите "
                        "./install.sh снова: установка продолжится.",
                        domain=domain,
                    ),
                )
            ctx.out(_("Жду сертификат для {domain}…", domain=domain))
            ctx.sleep(CERT_POLL_S)
    return True


def _tls_ready(ctx: Context, domain: str) -> bool:
    result = ctx.runner.run(
        [
            "openssl",
            "s_client",
            "-connect",
            "127.0.0.1:443",
            "-servername",
            domain,
            "-verify_hostname",
            domain,
        ],
        input="",
        check=False,
    )
    return TLS_OK in result.stdout


def _doctor(ctx: Context) -> bool:
    result = ctx.runner.run(
        [str(ctx.root / "scripts" / "doctor.sh")],
        cwd=ctx.root,
        check=False,
        env={i18n.ENV_VAR: i18n.get_lang()},
    )
    if result.stdout:
        ctx.out(result.stdout.rstrip())
    if result.code != 0:
        ctx.warn(
            _(
                "Проверка doctor нашла проблем: {code}. Подробности выше. Строка про сверку "
                "ноды (reconcile) на свежем стеке краснеет до первой сверки — подождите 5–6 минут "
                "и запустите «ocm status».",
                code=result.code,
            )
        )
    return True


def _backup(ctx: Context) -> bool:
    """Ключ шифрования копий и ежедневный таймер. Первую копию снимаем сразу: проверка, что
    всё работает, и точка возврата до первой настройки покупателем."""
    if not ctx.want_backup:
        ctx.notes.append(
            _(
                "Резервные копии выключены. Включить: sudo ocm backup-enable. "
                "Без копий потеря сервера означает потерю базы и CA (ключей всех клиентов)."
            )
        )
        return False
    existed = ctx.key_file.exists()
    key = backup.ensure_key(ctx.key_file)
    systemd.install(ctx.runner, ctx.root, unit_dir=ctx.unit_dir, ocm=ctx.ocm_link)
    if not existed:
        ctx.notes.append(
            _("КЛЮЧ ШИФРОВАНИЯ РЕЗЕРВНЫХ КОПИЙ (показан один раз):")
            + f"\n  {key}\n"
            + _(
                "Он же лежит в {path}. Сохраните его отдельно от сервера (менеджер паролей): "
                "без ключа копии не расшифровать, а при потере сервера этот файл пропадёт вместе с ним.",  # noqa: E501
                path=ctx.key_file,
            )
        )
    return True


def _ocm(ctx: Context) -> bool:
    ctx.runner.run(["ln", "-sfn", str(ctx.root / "deploy" / "ocm"), str(ctx.ocm_link)])
    return True


def build_steps() -> list[Step]:
    return [
        Step("env", _("Записываю настройки (.env)"), _env),
        Step("swap", _("Создаю swap"), _swap),
        Step("docker", _("Устанавливаю Docker"), _docker),
        Step("build", _("Собираю образы (около 5 минут)"), _build),
        Step("infra", _("Запускаю базы и применяю миграции"), _infra),
        Step("pki", _("Создаю удостоверяющий центр (CA)"), _pki),
        Step("admin", _("Создаю первого администратора"), _admin),
        Step("stack", _("Запускаю все сервисы"), _stack),
        Step("certs", _("Жду сертификаты Let's Encrypt (1–3 минуты)"), _certs),
        Step("ocm", _("Ставлю команду ocm"), _ocm),
        Step("backup", _("Настраиваю ежедневные резервные копии"), _backup),
        Step("doctor", _("Проверяю установку"), _doctor),
    ]


def run_steps(ctx: Context, steps: list[Step]) -> None:
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        label = f"[{index}/{total}] {step.title}"
        if ctx.state.is_done(step.name):
            ctx.out(_("{label} — уже сделано", label=label))
            continue
        if ctx.dry_run:
            ctx.out(_("[пробный запуск] {label}", label=label))
            continue
        ctx.out(label)
        try:
            performed = step.run(ctx)
        except CommandError as exc:
            raise StepError(
                _(
                    "Шаг {name} («{title}») не удался: {exc}",
                    name=step.name,
                    title=step.title,
                    exc=exc,
                )
            ) from exc
        except StepError as exc:
            raise StepError(
                _(
                    "Шаг {name} («{title}»): {message}",
                    name=step.name,
                    title=step.title,
                    message=exc.message,
                ),
                exc.hint,
            ) from exc
        if performed:
            ctx.state.mark(step.name)
