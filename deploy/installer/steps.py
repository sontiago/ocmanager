"""Шаги установки и файл состояния. Порядок шагов — тот же, что в `deploy/README.md`: базы,
CA, администратор, остальное. Каждый шаг после успеха отмечается в `deploy/.install-state`,
поэтому повторный запуск продолжает с места сбоя и не трогает сделанное."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from installer.config import render_env, write_env
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
    reuse_env: bool = False
    swapfile: Path = Path("/swapfile")
    fstab: Path = Path("/etc/fstab")
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
                    f"Сертификат для {domain} не выпущен за {CERT_TIMEOUT_S // 60} минут.",
                    f"Проверьте, что A-запись {domain} указывает на этот сервер и порт 80 "
                    "открыт снаружи (в том числе в облачном firewall провайдера). "
                    "Что говорит Caddy: docker compose logs caddy. "
                    "Лимит Let's Encrypt — 5 неудач в час. После исправления запустите "
                    "./install.sh снова: установка продолжится.",
                )
            ctx.out(f"Жду сертификат для {domain}…")
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
    result = ctx.runner.run([str(ctx.root / "scripts" / "doctor.sh")], cwd=ctx.root, check=False)
    if result.stdout:
        ctx.out(result.stdout.rstrip())
    if result.code != 0:
        ctx.warn(
            f"Проверка doctor нашла проблем: {result.code}. Подробности выше. Строка про сверку "
            "ноды (reconcile) на свежем стеке краснеет до первой сверки — подождите 5–6 минут "
            "и запустите «ocm status»."
        )
    return True


def build_steps() -> list[Step]:
    return [
        Step("env", "Записываю настройки (.env)", _env),
        Step("swap", "Создаю swap", _swap),
        Step("docker", "Устанавливаю Docker", _docker),
        Step("build", "Собираю образы (около 5 минут)", _build),
        Step("infra", "Запускаю базы и применяю миграции", _infra),
        Step("pki", "Создаю удостоверяющий центр (CA)", _pki),
        Step("admin", "Создаю первого администратора", _admin),
        Step("stack", "Запускаю все сервисы", _stack),
        Step("certs", "Жду сертификаты Let's Encrypt (1–3 минуты)", _certs),
        Step("doctor", "Проверяю установку", _doctor),
    ]


def run_steps(ctx: Context, steps: list[Step]) -> None:
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        label = f"[{index}/{total}] {step.title}"
        if ctx.state.is_done(step.name):
            ctx.out(f"{label} — уже сделано")
            continue
        if ctx.dry_run:
            ctx.out(f"[пробный запуск] {label}")
            continue
        ctx.out(label)
        try:
            performed = step.run(ctx)
        except CommandError as exc:
            raise StepError(f"Шаг {step.name} («{step.title}») не удался: {exc}") from exc
        except StepError as exc:
            raise StepError(f"Шаг {step.name} («{step.title}»): {exc.message}", exc.hint) from exc
        if performed:
            ctx.state.mark(step.name)
