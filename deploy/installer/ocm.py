"""Команда `ocm`: повседневное обслуживание установки. Вся логика здесь, а `deploy/ocm` —
тонкая bash-обёртка, которая находит каталог установки и запускает этот файл."""

import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from installer import backup, i18n, systemd
from installer.backup import BackupError, BackupPaths
from installer.config import validate_admin_password, write_private
from installer.i18n import _
from installer.prompts import Prompter, TerminalPrompter
from installer.runner import CommandError, Runner, SubprocessRunner
from installer.steps import State

CONFIRM_WORDS = {"ru": "ДА", "en": "YES"}


def usage() -> str:
    return _(
        """Использование: ocm <команда>

  status                         проверка состояния (doctor)
  logs [сервис] [-f]             журналы сервисов
  backup-enable                  включить ежедневные резервные копии
  backup                         резервная копия сейчас
  restore <файл> [--with-env] [--no-emergency]
                                 восстановить базу и CA из копии
  update                         обновить до свежей версии (с копией перед этим)
  rollback                       вернуться на версию до последнего обновления
  admin-chat <chat_id>           кому слать алерты в Telegram
  admin-password <логин>         сменить пароль администратора
"""
    )


ExecFn = Callable[[Sequence[str]], None]


@dataclass
class Ocm:
    runner: Runner
    prompter: Prompter
    paths: BackupPaths
    now: Callable[[], datetime]
    out: Callable[[str], None]
    exec_fn: ExecFn
    unit_dir: Path = systemd.UNIT_DIR

    @property
    def root(self) -> Path:
        return self.paths.root

    @property
    def deploy(self) -> Path:
        return self.paths.deploy

    @property
    def previous(self) -> Path:
        return self.deploy / ".previous-rev"

    def compose(self, *args: str, input: str | None = None, check: bool = True):  # type: ignore[no-untyped-def]
        return self.runner.run(
            ["docker", "compose", *args], cwd=self.deploy, input=input, check=check
        )

    def cli(self, *args: str, input: str | None = None, check: bool = True):  # type: ignore[no-untyped-def]
        return self.compose("run", "--rm", "-T", "cli", *args, input=input, check=check)

    def git(self, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        return self.runner.run(["git", *args], cwd=self.root, check=check)

    def confirm_word(self, key: str, warning: str) -> bool:
        word = CONFIRM_WORDS[i18n.get_lang()]
        answer = self.prompter.ask(
            key, warning + "\n" + _("Для продолжения введите «{word}»", word=word)
        )
        return answer.strip() in CONFIRM_WORDS.values()

    # --- команды ---

    def status(self) -> int:
        result = self.runner.run(
            [str(self.root / "scripts" / "doctor.sh")],
            cwd=self.root,
            check=False,
            env={i18n.ENV_VAR: i18n.get_lang()},
        )
        self.out(result.stdout.rstrip())
        return result.code

    def logs(self, args: list[str]) -> int:
        follow = "-f" in args
        services = [a for a in args if a != "-f"]
        os.chdir(self.deploy)
        self.exec_fn(
            ["docker", "compose", "logs", "--tail", "200", *(["-f"] if follow else []), *services]
        )
        return 0

    def _alert(self, reason: str) -> None:
        try:
            self.cli("notify", "backup-failed", "--reason", reason[:300])
        except CommandError as exc:
            self.out(_("Алерт админу не поставлен: {exc}", exc=exc))

    def backups_enabled(self) -> bool:
        return self.paths.key_file.exists()

    def backup_enable(self) -> int:
        existed = self.backups_enabled()
        try:
            key = backup.ensure_key(self.paths.key_file)
            systemd.install(self.runner, self.root, unit_dir=self.unit_dir, ocm=systemd.OCM_LINK)
        except (BackupError, CommandError, OSError) as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            return 1
        state = State(self.deploy / ".install-state")
        remote = self.prompter.ask(
            "backup_remote",
            _(
                "Куда дополнительно копировать: пользователь@сервер:/путь или каталог. Enter — никуда"  # noqa: E501
            ),
            default=state.answers().get("backup_remote", ""),
            validate=backup.validate_remote,
        )
        state.remember(backup_enabled="yes", backup_remote=remote)
        if not existed:
            self.out(
                _("КЛЮЧ ШИФРОВАНИЯ КОПИЙ (показан один раз): {key}", key=key)
                + "\n"
                + _(
                    "Он лежит в {path}. Сохраните его отдельно от сервера: "
                    "без него копии не расшифровать.",
                    path=self.paths.key_file,
                )
            )
        self.out(_("Ежедневные копии включены (03:30). Первая копия сейчас: ocm backup"))
        return 0

    def make_backup(self) -> Path | None:
        """Копия + уборка + метка + (необязательно) вторая копия на другой сервер. При любой
        ошибке — алерт админу и None; старые копии не удаляются."""
        if not self.backups_enabled():
            self.out(_("Резервные копии не включены. Включить: sudo ocm backup-enable"))
            return None
        try:
            path = backup.create(self.paths, self.runner, self.now())
            backup.record_success(self.paths.backup_dir, self.now())
            backup.prune(self.paths.backup_dir)
            remote = State(self.deploy / ".install-state").answers().get("backup_remote", "")
            if remote:
                backup.copy_offsite(path, remote, self.runner)
        except BackupError as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            self._alert(str(exc))
            return None
        self.out(_("Резервная копия: {path}", path=path))
        return path

    def backup(self) -> int:
        return 0 if self.make_backup() else 1

    def restore(self, args: list[str]) -> int:
        flags = {a for a in args if a.startswith("--")}
        files = [a for a in args if not a.startswith("--")]
        if len(files) != 1 or flags - {"--with-env", "--no-emergency"}:
            self.out(usage())
            return 2
        path = Path(files[0])
        try:
            manifest = backup.verify(path, self.paths.key_file, self.runner)
        except BackupError as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            return 1
        warning = _(
            "Копия от {created} (версия {version}).\n"
            "Восстановление ЗАМЕНИТ текущие данные: базу и CA. Сервисы будут остановлены.",
            created=manifest.created,
            version=manifest.version,
        )
        if not self.confirm_word("restore_confirm", warning):
            self.out(_("Отменено."))
            return 1
        try:
            backup.restore(
                path,
                self.paths,
                self.runner,
                self.now(),
                restore_env="--with-env" in flags,
                emergency="--no-emergency" not in flags,
            )
        except BackupError as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            return 1
        self.out(_("Данные восстановлены."))
        return self.status()

    def update(self) -> int:
        try:
            if self.git("status", "--porcelain").stdout.strip():
                self.out(
                    _(
                        "В каталоге установки есть локальные изменения (git status). Обновление "
                        "остановлено: сохраните или отмените их и повторите."
                    )
                )
                return 1
            branch = self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            if branch == "HEAD":
                self.out(
                    _(
                        "Сейчас выбрана не ветка, а конкретный коммит (после отката). "
                        "Вернитесь на ветку: git switch <ветка> (имя — в deploy/.previous-rev)."
                    )
                )
                return 1
            self.git("fetch")
            head = self.git("rev-parse", "HEAD").stdout.strip()
            upstream = self.git("rev-parse", "@{u}").stdout.strip()
            if head == upstream:
                self.out(_("Уже установлена последняя версия."))
                return 0
            if self.git("merge-base", "--is-ancestor", "HEAD", "@{u}", check=False).code != 0:
                self.out(
                    _(
                        "Обновление невозможно без слияния: в вашей копии есть коммиты, которых нет "  # noqa: E501
                        "в репозитории. Ничего не изменено."
                    )
                )
                return 1
        except CommandError as exc:
            self.out(_("Не удалось проверить репозиторий: {exc}", exc=exc))
            return 1
        saved: Path | None = None
        if self.backups_enabled():
            saved = self.make_backup()
            if saved is None:
                self.out(_("Копия не создана — обновление остановлено, ничего не изменено."))
                return 1
        elif not self.prompter.confirm(
            "update_without_backup",
            _(
                "Резервные копии не включены: откатить базу после обновления будет нечем. "
                "Обновить без копии?"
            ),
            default=False,
        ):
            self.out(_("Отменено. Включить копии: sudo ocm backup-enable"))
            return 1
        write_private(
            self.previous,
            json.dumps({"rev": head, "branch": branch, "backup": str(saved) if saved else ""}),
        )
        try:
            self.git("pull", "--ff-only")
            self.compose("build")
            self.compose("up", "-d")
        except CommandError as exc:
            self.out(
                _("Ошибка при обновлении: {exc}\nВернуть прежнюю версию: ocm rollback", exc=exc)
            )
            return 1
        if self.status() != 0:
            self.out(
                _("Проверка после обновления нашла проблемы. Вернуть прежнюю версию: ocm rollback")
            )
            return 1
        self.out(_("Обновление завершено."))
        return 0

    def rollback(self) -> int:
        try:
            record = json.loads(self.previous.read_text())
            rev, branch = record["rev"], record["branch"]
            saved = Path(record["backup"]) if record["backup"] else None
        except (OSError, ValueError, KeyError):
            self.out(
                _(
                    "Нет записи о предыдущей версии: откатывать нечего "
                    "(откат возможен после ocm update)."
                )
            )
            return 1
        if not self.confirm_word(
            "rollback_confirm",
            _("Вернуть код на версию {rev} и пересобрать сервисы.", rev=rev[:12]),
        ):
            self.out(_("Отменено."))
            return 1
        try:
            self.git("checkout", rev)
            self.compose("build")
            self.compose("up", "-d")
        except CommandError as exc:
            self.out(_("Ошибка отката: {exc}", exc=exc))
            return 1
        self.out(
            _(
                "Код возвращён на {rev}. Чтобы потом снова обновляться: git switch {branch}",
                rev=rev[:12],
                branch=branch,
            )
        )
        if saved is not None and self.prompter.confirm(
            "rollback_restore_db",
            _(
                "Восстановить и данные из копии до обновления ({name})? Изменения после "
                "обновления будут потеряны.",
                name=saved.name,
            ),
            default=False,
        ):
            try:
                backup.restore(saved, self.paths, self.runner, self.now())
            except BackupError as exc:
                self.out(_("Ошибка: {exc}", exc=exc))
                return 1
            self.out(_("Данные восстановлены."))
        return self.status()

    def admin_chat(self, args: list[str]) -> int:
        if len(args) != 1 or not args[0].lstrip("-").isdigit():
            self.out(
                _("Использование: ocm admin-chat <chat_id>  (число из ответа бота на /whoami)")
            )
            return 2
        try:
            result = self.cli("settings", "admin-chat", args[0])
        except CommandError as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            return 1
        self.out(result.stdout.strip())
        return 0

    def admin_password(self, args: list[str]) -> int:
        if len(args) != 1:
            self.out(_("Использование: ocm admin-password <логин>"))
            return 2
        password = self.prompter.ask_secret(
            "admin_password",
            _("Новый пароль (не короче 12 символов)"),
            validate=validate_admin_password,
        )
        try:
            self.cli("admin", "passwd", args[0], "--password-stdin", input=password + "\n")
        except CommandError as exc:
            self.out(_("Ошибка: {exc}", exc=exc))
            return 1
        self.out(_("Пароль изменён."))
        return 0


def main(
    argv: Sequence[str],
    *,
    runner: Runner | None = None,
    prompter: Prompter | None = None,
    paths: BackupPaths | None = None,
    now: Callable[[], datetime] | None = None,
    out: Callable[[str], None] = print,
    exec_fn: ExecFn | None = None,
    unit_dir: Path = systemd.UNIT_DIR,
) -> int:
    root = Path(__file__).resolve().parents[2]
    ocm = Ocm(
        runner=runner or SubprocessRunner(),
        prompter=prompter or TerminalPrompter(),
        paths=paths or BackupPaths(root=root),
        now=now or datetime.now().astimezone,
        out=out,
        unit_dir=unit_dir,
        exec_fn=exec_fn or (lambda cmd: os.execvp(cmd[0], list(cmd))),  # noqa: S606
    )
    chosen = i18n.from_env() or State(ocm.deploy / ".install-state").answers().get("lang")
    if chosen in i18n.LANGUAGES:
        i18n.set_lang(chosen)
    command, args = (argv[0], list(argv[1:])) if argv else ("", [])
    if command == "status":
        return ocm.status()
    if command == "logs":
        return ocm.logs(args)
    if command == "backup-enable":
        return ocm.backup_enable()
    if command == "backup":
        return ocm.backup()
    if command == "restore":
        return ocm.restore(args)
    if command == "update":
        return ocm.update()
    if command == "rollback":
        return ocm.rollback()
    if command == "admin-chat":
        return ocm.admin_chat(args)
    if command == "admin-password":
        return ocm.admin_password(args)
    out(usage())
    return 0 if command in ("", "-h", "--help", "help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
