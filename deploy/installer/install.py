"""Мастер установки: `sudo ./install.sh`. Проверяет сервер, задаёт вопросы, выполняет шаги и
печатает итог. Всё внешнее (команды, сеть, ввод, чтение системы) подаётся снаружи — так весь
сценарий проходит тестами без Docker и интернета."""

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from installer import checks, config
from installer.checks import Finding, SystemInfo
from installer.prompts import AnswersPrompter, Prompter, TerminalPrompter
from installer.runner import Net, NetError, Runner, SubprocessRunner, SystemNet
from installer.steps import Context, State, StepError, build_steps, run_steps

TUNNEL_PORT = 8080


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="install.sh", description="Установка ocmanager")
    parser.add_argument("--answers", metavar="FILE", help="ответы на вопросы из JSON-файла")
    parser.add_argument("--dry-run", action="store_true", help="показать план, ничего не меняя")
    parser.add_argument(
        "--yes", action="store_true", help="на вопросы «да/нет» отвечать по умолчанию"
    )
    return parser.parse_args(argv)


class _AssumeDefaults:
    """`--yes`: подтверждения принимаются по умолчанию, остальное спрашивается как обычно."""

    def __init__(self, inner: Prompter) -> None:
        self._inner = inner
        self.say = inner.say
        self.ask = inner.ask
        self.ask_secret = inner.ask_secret

    def confirm(self, key: str, text: str, *, default: bool = True) -> bool:
        return default


def prompter_from_args(argv: Sequence[str] | None) -> Prompter:
    args = parse_args(argv)
    if args.answers:
        prompter: Prompter = AnswersPrompter(json.loads(Path(args.answers).read_text()))
    else:
        prompter = TerminalPrompter()
    return _AssumeDefaults(prompter) if args.yes else prompter


def _show_findings(say: Callable[[str], None], findings: Sequence[Finding]) -> None:
    for f in findings:
        if f.ok:
            say(f"  ✓ {f.title}")
        else:
            say(f"  ✗ {f.title}")
            say(f"      {f.hint}")


class _Stop(Exception):
    """Остановка мастера по понятной причине (код выхода 1)."""


def _look_at_the_server(
    prompter: Prompter, runner: Runner, net: Net, system: SystemInfo, state: State
) -> tuple[bool, bool]:
    """Проверки системы. Возвращает (ставить Docker, создать swap)."""
    prompter.say("Проверяю сервер…")
    findings = checks.run_all(runner, net, system, our_containers_running=state.is_done("stack"))
    _show_findings(prompter.say, findings)
    blockers = checks.blockers(findings)
    if blockers:
        prompter.say("")
        prompter.say("Установка невозможна, пока не исправлено:")
        for f in blockers:
            prompter.say(f"  • {f.title}: {f.hint}")
        raise _Stop
    codes = {f.code for f in findings if not f.ok}
    want_docker = False
    if "docker_missing" in codes:
        want_docker = prompter.confirm(
            "install_docker",
            "Docker не найден. Установить docker.io и docker-compose-v2 из репозитория системы?",
            default=True,
        )
        if not want_docker:
            prompter.say(
                "Без Docker продолжить нельзя. Установите его и запустите ./install.sh снова."
            )
            raise _Stop
    want_swap = False
    if "swap_needed" in codes:
        want_swap = prompter.confirm(
            "create_swap",
            "Памяти меньше 2 ГБ и нет swap: сборка может упасть. Создать swap 2 ГБ?",
            default=True,
        )
    return want_docker, want_swap


def _ask_bot(prompter: Prompter, net: Net) -> tuple[str, str]:
    """Токен бота и его имя: токен проверяется у Telegram, имя нужно для реферальной ссылки."""
    while True:
        token = prompter.ask(
            "bot_token",
            "Токен бота (его выдаёт @BotFather)",
            validate=config.validate_bot_token,
        )
        try:
            return token, net.telegram_get_me(token)
        except NetError as exc:
            if not exc.unreachable:
                prompter.say(f"{exc}. Проверьте токен и введите снова.")
                continue
            prompter.say("Не удалось связаться с Telegram, чтобы проверить токен.")
            if prompter.confirm(
                "continue_without_bot_name",
                "Продолжить без проверки (реферальная ссылка не будет собираться, "
                "имя бота можно вписать в .env позже)?",
                default=True,
            ):
                return token, ""


def _ask_values(prompter: Prompter, net: Net, state: State) -> dict[str, str]:
    remembered = state.answers()
    say = prompter.say
    say("")
    say("Теперь несколько вопросов о вашем сервере.")
    app = prompter.ask(
        "domain_app",
        "Домен для Mini App и вебхуков (например app.example.com)",
        default=remembered.get("domain_app"),
        validate=config.normalize_domain,
    )

    def vpn_domain(raw: str) -> str:
        domain = config.normalize_domain(raw)
        config.validate_distinct_domains(app, domain)
        return domain

    vpn = prompter.ask(
        "domain_vpn",
        "Домен для VPN (другой, например vpn.example.com)",
        default=remembered.get("domain_vpn"),
        validate=vpn_domain,
    )
    email = prompter.ask(
        "acme_email",
        "Почта для уведомлений Let's Encrypt",
        default=remembered.get("acme_email"),
        validate=config.validate_email,
    )
    token, bot_name = _ask_bot(prompter, net)
    tribute = prompter.ask(
        "tribute_key", "Ключ API Tribute (Enter — пропустить, вписать позже)", default=""
    )
    return {
        "DOMAIN_APP": app,
        "DOMAIN_VPN": vpn,
        "ACME_EMAIL": email,
        **config.generate_secrets(),
        "OCM_BOT_TOKEN": token,
        "OCM_BOT_USERNAME": bot_name,
        "OCM_TRIBUTE_API_KEY": tribute,
    }


def _choose_env(
    prompter: Prompter, net: Net, state: State, env_path: Path
) -> tuple[dict[str, str], bool]:
    """Значения для .env: прежние (если есть и покупатель согласен) или новые из вопросов."""
    if env_path.exists():
        existing = config.parse_env(env_path.read_text())
        usable = bool(existing.get("DOMAIN_APP") and existing.get("DOMAIN_VPN"))
        if usable and state.is_done("infra"):
            # Пароль Postgres уже зашит в созданный том: новый .env сделал бы базу недоступной.
            prompter.say("Базы уже созданы, поэтому настройки (.env) остаются прежними.")
            return existing, True
        if usable and prompter.confirm(
            "use_existing_env", "Найден готовый .env. Использовать его без вопросов?", default=True
        ):
            return existing, True
    return _ask_values(prompter, net, state), False


def _check_domains(prompter: Prompter, net: Net, values: dict[str, str]) -> None:
    public_ip = net.public_ip()
    findings = [
        checks.check_dns(net, values[key], public_ip) for key in ("DOMAIN_APP", "DOMAIN_VPN")
    ]
    problems = [f for f in findings if not f.ok]
    _show_findings(prompter.say, findings)
    if not problems:
        return
    if any(f.code == "dns_missing" for f in problems):
        prompter.say(
            "Без A-записей сертификаты не выпустятся. Создайте их и запустите ./install.sh снова."
        )
        raise _Stop
    if not prompter.confirm("dns_continue", "Продолжить всё равно?", default=False):
        raise _Stop


def _ask_admin(prompter: Prompter, state: State) -> tuple[str, str, bool]:
    """(логин, пароль, пароль сгенерирован). Если администратор уже создан — не спрашиваем."""
    remembered = state.answers()
    if state.is_done("admin"):
        return remembered.get("admin_user", "owner"), "", False
    user = prompter.ask(
        "admin_user",
        "Логин администратора панели",
        default=remembered.get("admin_user", "owner"),
        validate=config.validate_admin_username,
    )
    if prompter.confirm(
        "generate_password", "Сгенерировать надёжный пароль администратора?", default=True
    ):
        return user, config.generate_password(), True
    password = prompter.ask_secret(
        "admin_password",
        "Пароль администратора (не короче 12 символов)",
        validate=config.validate_admin_password,
    )
    return user, password, False


def _final_screen(
    say: Callable[[str], None],
    values: dict[str, str],
    public_ip: str | None,
    admin_user: str,
    generated_password: str | None,
    notes: Sequence[str],
    *,
    dry_run: bool,
) -> None:
    app, vpn = values["DOMAIN_APP"], values["DOMAIN_VPN"]
    host = public_ip or app
    say("")
    say("=" * 64)
    if dry_run:
        say("Это был пробный запуск: ничего не установлено и не изменено.")
        return
    say("Готово. ocmanager установлен.")
    say("=" * 64)
    say(f"  Mini App:    https://{app}")
    say(f"  VPN-шлюз:    https://{vpn}")
    say("")
    say("Админка открывается только через SSH-туннель. На своём компьютере выполните:")
    say(f"  ssh -L {TUNNEL_PORT}:127.0.0.1:{TUNNEL_PORT} пользователь@{host}")
    say(f"и откройте в браузере http://localhost:{TUNNEL_PORT}/")
    say(f"Логин: {admin_user}")
    if generated_password:
        say(f"Пароль: {generated_password}")
        say("(пароль показан один раз — запишите его сейчас)")
    say("")
    say("Что сделать дальше:")
    say(f"  1. @BotFather → /myapps → ваше приложение → Edit Web App URL → https://{app}")
    say("  2. Напишите своему боту /whoami, он ответит числом. Затем на сервере:")
    say("       ocm admin-chat <это число>      (так вы начнёте получать алерты)")
    say("  3. В админке создайте тарифы; ключ Tribute впишите в deploy/.env (OCM_TRIBUTE_API_KEY).")
    for note in notes:
        say("")
        say(note)
    say("")
    say("Состояние сервера: ocm status. Справка: deploy/INSTALL.md")


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    net: Net | None = None,
    prompter: Prompter | None = None,
    root: Path | None = None,
    system: SystemInfo | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    swapfile: Path = Path("/swapfile"),
    fstab: Path = Path("/etc/fstab"),
) -> int:
    args = parse_args(argv)
    runner = runner or SubprocessRunner()
    net = net or SystemNet()
    prompter = prompter or prompter_from_args(argv)
    root = root or Path(__file__).resolve().parents[2]
    system = system or SystemInfo.read(root)
    state = State(root / "deploy" / ".install-state")
    say = prompter.say

    say("ocmanager: установка")
    say("")
    try:
        want_docker, want_swap = _look_at_the_server(prompter, runner, net, system, state)
        values, reuse = _choose_env(prompter, net, state, root / "deploy" / ".env")
        if not state.is_done("stack"):
            _check_domains(prompter, net, values)
        admin_user, admin_password, generated = _ask_admin(prompter, state)
    except _Stop:
        return 1

    if not args.dry_run:
        state.remember(
            domain_app=values["DOMAIN_APP"],
            domain_vpn=values["DOMAIN_VPN"],
            acme_email=values["ACME_EMAIL"],
            admin_user=admin_user,
        )

    ctx = Context(
        runner=runner,
        net=net,
        root=root,
        values=values,
        admin_user=admin_user,
        admin_password=admin_password,
        state=state,
        sleep=sleep,
        clock=clock,
        out=say,
        warn=say,
        dry_run=args.dry_run,
        want_swap=want_swap,
        want_docker=want_docker,
        reuse_env=reuse,
        swapfile=swapfile,
        fstab=fstab,
    )
    say("")
    try:
        run_steps(ctx, build_steps())
    except StepError as exc:
        say("")
        say(f"Установка остановилась. {exc}")
        say("")
        say("Исправьте причину и запустите ./install.sh снова: установка продолжится с этого шага.")
        return 1
    _final_screen(
        say,
        values,
        net.public_ip(),
        admin_user,
        admin_password if generated else None,
        ctx.notes,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
