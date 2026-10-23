import json
from pathlib import Path

import pytest

from installer import install, steps
from installer.checks import SystemInfo
from installer.config import generate_secrets, parse_env, write_env
from installer.runner import FakeNet, FakeRunner, Result
from installer.tests.conftest import GIB, UBUNTU_2204, Keyed, meminfo

TOKEN = "123456789:AAH-abcdefghijklmnopqrstuvwxyz_01"
PASSWORD = "correct-horse-battery"
HOST = "203.0.113.10"

ANSWERS = {
    "domain_app": "HTTPS://App.Example.com/",
    "domain_vpn": "vpn.example.com",
    "acme_email": "me@example.com",
    "bot_token": TOKEN,
    "admin_user": "owner",
    "generate_password": False,
    "admin_password": PASSWORD,
    "tribute_key": "",
    "backup_remote": "",
}


def system(**over) -> SystemInfo:  # type: ignore[no-untyped-def]
    base = dict(
        os_release=UBUNTU_2204,
        euid=0,
        python=(3, 12, 0),
        meminfo=meminfo(4),
        free_bytes=50 * GIB,
    )
    return SystemInfo(**{**base, **over})


def good_net() -> FakeNet:
    return FakeNet(
        public_ip=HOST,
        a_records={"app.example.com": [HOST], "vpn.example.com": [HOST]},
        bots={TOKEN: "ocbot"},
    )


def good_runner() -> FakeRunner:
    runner = FakeRunner()
    runner.on("docker version", Result(0, "27.1.1\n"))
    runner.on("docker compose version", Result(0, "2.29.1\n"))
    runner.on("-ltnp", Result(0, ""))
    runner.on("-lunp", Result(0, ""))
    runner.on("s_client", Result(0, "Verify return code: 0 (ok)\n"))
    runner.on("doctor.sh", Result(0, "всё в порядке\n"))
    return runner


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, s: float) -> None:
        self.now += s

    def monotonic(self) -> float:
        return self.now


def run_main(root: Path, answers: dict, *, runner=None, net=None, sys_info=None, argv=()):  # type: ignore[no-untyped-def]
    prompter = Keyed(answers)
    clock = Clock()
    runner = runner or good_runner()
    code = install.main(
        list(argv),
        runner=runner,
        net=net or good_net(),
        prompter=prompter,
        root=root,
        system=sys_info or system(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        swapfile=root / "swapfile",
        fstab=root / "fstab",
    )
    return code, prompter, runner


def screen(prompter: Keyed) -> str:
    return "\n".join(prompter.said)


def test_a_full_install_from_answers(root: Path) -> None:
    code, prompter, runner = run_main(root, ANSWERS)
    assert code == 0, screen(prompter)
    env = parse_env((root / "deploy" / ".env").read_text())
    assert env["DOMAIN_APP"] == "app.example.com"  # нормализован
    assert env["DOMAIN_VPN"] == "vpn.example.com"
    assert env["ACME_EMAIL"] == "me@example.com"
    assert env["OCM_BOT_TOKEN"] == TOKEN
    assert env["OCM_BOT_USERNAME"] == "ocbot"  # взят у Telegram
    assert len(env["POSTGRES_PASSWORD"]) == 48
    assert any("pki init" in c for c in runner.joined())
    index = next(i for i, c in enumerate(runner.joined()) if "admin create" in c)
    assert runner.inputs[index] == PASSWORD + "\n"


def test_the_final_screen_has_the_addresses_and_next_steps_but_no_secrets(root: Path) -> None:
    code, prompter, _ = run_main(root, ANSWERS)
    text = screen(prompter)
    assert "https://app.example.com" in text
    assert "ssh -L 8080:127.0.0.1:8080" in text
    assert "BotFather" in text and "/whoami" in text and "ocm admin-chat" in text
    assert "owner" in text
    env = parse_env((root / "deploy" / ".env").read_text())
    for secret in (PASSWORD, TOKEN, env["OCM_SECRET_KEY"], env["POSTGRES_PASSWORD"]):
        assert secret not in text


def test_a_generated_admin_password_is_shown_once_on_the_final_screen(root: Path) -> None:
    answers = {**ANSWERS, "generate_password": True}
    code, prompter, runner = run_main(root, answers)
    assert code == 0
    index = next(i for i, c in enumerate(runner.joined()) if "admin create" in c)
    generated = (runner.inputs[index] or "").strip()
    assert len(generated) >= 12
    assert screen(prompter).count(generated) == 1


def test_dry_run_does_not_mutate_anything(root: Path) -> None:
    code, prompter, runner = run_main(root, ANSWERS, argv=["--dry-run"])
    assert code == 0
    mutating = [
        c
        for c in runner.joined()
        if c.startswith(("docker compose", "apt-get", "fallocate")) and "version" not in c
    ]
    assert mutating == []
    assert not (root / "deploy" / ".env").exists()
    assert not (root / "deploy" / ".install-state").exists()
    assert "пробный запуск" in screen(prompter)


def test_a_blocking_check_stops_before_any_question(root: Path) -> None:
    runner = good_runner()
    runner.calls.clear()
    busy = FakeRunner()
    busy.on("docker version", Result(0, "27.1.1\n"))
    busy.on("docker compose version", Result(0, "2.29.1\n"))
    busy.on("-ltnp", Result(0, 'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=6))\n'))
    busy.on("-lunp", Result(0, ""))
    code, prompter, _ = run_main(root, ANSWERS, runner=busy)
    assert code == 1
    assert prompter.asked == []
    assert "nginx" in screen(prompter)
    assert not (root / "deploy" / ".env").exists()


def test_not_root_stops_immediately(root: Path) -> None:
    code, prompter, _ = run_main(root, ANSWERS, sys_info=system(euid=1000))
    assert code == 1 and prompter.asked == []
    assert "sudo" in screen(prompter)


def test_a_wrong_bot_token_is_asked_again(root: Path) -> None:
    answers = {**ANSWERS, "bot_token": ["999999:wrongtokenwrongtokenwrongtoken", TOKEN]}
    code, prompter, _ = run_main(root, answers)
    assert code == 0
    assert prompter.asked.count("bot_token") == 2
    assert "не принял" in screen(prompter)


def test_a_malformed_bot_token_is_asked_again_without_calling_telegram(root: Path) -> None:
    answers = {**ANSWERS, "bot_token": ["garbage", TOKEN]}
    code, prompter, _ = run_main(root, answers)
    assert code == 0 and prompter.asked.count("bot_token") == 2


def test_an_unreachable_telegram_can_be_skipped_without_the_bot_name(root: Path) -> None:
    net = FakeNet(
        public_ip=HOST,
        a_records={"app.example.com": [HOST], "vpn.example.com": [HOST]},
        telegram_down=True,
    )
    answers = {**ANSWERS, "continue_without_bot_name": True}
    code, prompter, _ = run_main(root, answers, net=net)
    assert code == 0
    env = parse_env((root / "deploy" / ".env").read_text())
    assert env["OCM_BOT_USERNAME"] == ""
    assert "continue_without_bot_name" in prompter.asked


def test_an_unreachable_telegram_declined_asks_for_the_token_again(root: Path) -> None:
    net = FakeNet(
        public_ip=HOST,
        a_records={"app.example.com": [HOST], "vpn.example.com": [HOST]},
        bots={TOKEN: "ocbot"},
    )
    flaky = {"down": True}
    original = net.telegram_get_me

    def get_me(token: str) -> str:
        if flaky.pop("down", False):
            net.telegram_down = True
            try:
                return original(token)
            finally:
                net.telegram_down = False
        return original(token)

    net.telegram_get_me = get_me  # type: ignore[method-assign]
    answers = {**ANSWERS, "bot_token": [TOKEN, TOKEN], "continue_without_bot_name": False}
    code, prompter, _ = run_main(root, answers, net=net)
    assert code == 0
    assert prompter.asked.count("bot_token") == 2
    assert parse_env((root / "deploy" / ".env").read_text())["OCM_BOT_USERNAME"] == "ocbot"


def test_equal_domains_are_rejected_and_asked_again(root: Path) -> None:
    answers = {**ANSWERS, "domain_vpn": ["app.example.com", "vpn.example.com"]}
    code, prompter, _ = run_main(root, answers)
    assert code == 0
    assert "разными" in screen(prompter)


def test_a_dns_mismatch_stops_unless_the_user_insists(root: Path) -> None:
    net = FakeNet(
        public_ip=HOST,
        a_records={"app.example.com": ["198.51.100.7"], "vpn.example.com": [HOST]},
        bots={TOKEN: "ocbot"},
    )
    code, prompter, runner = run_main(root, {**ANSWERS, "dns_continue": False}, net=net)
    assert code == 1
    assert "198.51.100.7" in screen(prompter)
    assert not any("build" in c for c in runner.joined())

    code, _, _ = run_main(root, {**ANSWERS, "dns_continue": True}, net=net)
    assert code == 0


def test_a_missing_a_record_cannot_be_overridden(root: Path) -> None:
    net = FakeNet(public_ip=HOST, a_records={"vpn.example.com": [HOST]}, bots={TOKEN: "ocbot"})
    code, prompter, _ = run_main(root, {**ANSWERS, "dns_continue": True}, net=net)
    assert code == 1
    assert "A-запис" in screen(prompter)


def test_an_existing_env_can_be_reused_without_domain_questions(root: Path) -> None:
    values = {
        **generate_secrets(),
        "DOMAIN_APP": "old.example.com",
        "DOMAIN_VPN": "oldvpn.example.com",
        "ACME_EMAIL": "x@example.com",
        "OCM_BOT_TOKEN": TOKEN,
        "OCM_BOT_USERNAME": "ocbot",
    }
    from installer.config import render_env

    write_env(root / "deploy" / ".env", render_env(values, root / "deploy" / ".env.example"))
    before = (root / "deploy" / ".env").read_text()
    net = FakeNet(
        public_ip=HOST, a_records={"old.example.com": [HOST], "oldvpn.example.com": [HOST]}
    )
    answers = {
        "use_existing_env": True,
        "admin_user": "owner",
        "generate_password": False,
        "admin_password": PASSWORD,
    }
    code, prompter, _ = run_main(root, answers, net=net)
    assert code == 0, screen(prompter)
    assert "domain_app" not in prompter.asked
    assert (root / "deploy" / ".env").read_text() == before


def test_secrets_are_never_regenerated_once_the_databases_exist(root: Path) -> None:
    """Пароль Postgres зашит в уже созданный том: новый .env сделал бы базу недоступной."""
    values = {
        **generate_secrets(),
        "DOMAIN_APP": "app.example.com",
        "DOMAIN_VPN": "vpn.example.com",
        "ACME_EMAIL": "x@example.com",
        "OCM_BOT_TOKEN": TOKEN,
        "OCM_BOT_USERNAME": "ocbot",
    }
    from installer.config import render_env

    write_env(root / "deploy" / ".env", render_env(values, root / "deploy" / ".env.example"))
    state = steps.State(root / "deploy" / ".install-state")
    for name in ("env", "build", "infra"):
        state.mark(name)
    answers = {"admin_user": "owner", "generate_password": False, "admin_password": PASSWORD}
    code, prompter, _ = run_main(root, answers)
    assert code == 0, screen(prompter)
    assert "use_existing_env" not in prompter.asked  # выбора нет: только сохранить
    assert (
        parse_env((root / "deploy" / ".env").read_text())["POSTGRES_PASSWORD"]
        == values["POSTGRES_PASSWORD"]
    )


def test_a_missing_docker_can_be_installed_with_consent(root: Path) -> None:
    runner = good_runner()
    missing = FakeRunner()
    missing.on("docker version", Result(127, "", "docker: command not found"))
    missing.on("docker compose version", Result(127, "", "not found"))
    for needle, result in (
        ("-ltnp", Result(0, "")),
        ("-lunp", Result(0, "")),
        ("s_client", Result(0, "Verify return code: 0 (ok)")),
        ("doctor.sh", Result(0, "")),
    ):
        missing.on(needle, result)
    code, prompter, _ = run_main(root, {**ANSWERS, "install_docker": True}, runner=missing)
    assert code == 0, screen(prompter)
    assert "apt-get update" in missing.joined()
    assert runner is not None


def test_a_missing_docker_declined_stops(root: Path) -> None:
    missing = FakeRunner()
    missing.on("docker version", Result(127, "", "docker: command not found"))
    missing.on("-ltnp", Result(0, ""))
    missing.on("-lunp", Result(0, ""))
    code, prompter, _ = run_main(root, {**ANSWERS, "install_docker": False}, runner=missing)
    assert code == 1
    assert "Docker" in screen(prompter)
    assert not (root / "deploy" / ".env").exists()


def test_low_memory_offers_swap(root: Path) -> None:
    code, prompter, runner = run_main(
        root, {**ANSWERS, "create_swap": True}, sys_info=system(meminfo=meminfo(1))
    )
    assert code == 0
    assert any("fallocate" in c for c in runner.joined())
    assert "create_swap" in prompter.asked


def test_low_memory_swap_declined_continues_without_it(root: Path) -> None:
    code, _, runner = run_main(
        root, {**ANSWERS, "create_swap": False}, sys_info=system(meminfo=meminfo(1))
    )
    assert code == 0
    assert not any("fallocate" in c for c in runner.joined())


def test_a_failed_step_prints_how_to_continue_and_exits_nonzero(root: Path) -> None:
    runner = good_runner()
    failing = FakeRunner()
    failing.on("pki init", Result(1, "", "boom"))
    for needle, result in (
        ("docker version", Result(0, "27.1.1\n")),
        ("docker compose version", Result(0, "2.29.1\n")),
        ("-ltnp", Result(0, "")),
        ("-lunp", Result(0, "")),
    ):
        failing.on(needle, result)
    code, prompter, _ = run_main(root, ANSWERS, runner=failing)
    assert code == 1
    assert "./install.sh" in screen(prompter)
    assert "pki" in screen(prompter)
    assert runner is not None


def test_answers_file_drives_the_installer(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = root / "answers.json"
    path.write_text(json.dumps(ANSWERS))
    prompter = install.prompter_from_args(["--answers", str(path)])
    assert prompter.ask("domain_vpn", "?") == "vpn.example.com"


def test_non_secret_answers_are_remembered_as_defaults(root: Path) -> None:
    run_main(root, ANSWERS)
    remembered = steps.State(root / "deploy" / ".install-state").answers()
    assert remembered["domain_app"] == "app.example.com"
    assert remembered["admin_user"] == "owner"
    assert PASSWORD not in json.dumps(remembered)
    assert TOKEN not in json.dumps(remembered)
