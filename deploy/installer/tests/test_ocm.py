import json
from datetime import timedelta
from pathlib import Path

import pytest

from installer import backup, ocm
from installer.backup import BackupPaths
from installer.prompts import ScriptedPrompter
from installer.runner import CommandError, FakeRunner, Result
from installer.tests.conftest import NOW, Stack, requires_openssl


@pytest.fixture
def paths(root: Path, tmp_path: Path) -> BackupPaths:
    (root / "deploy" / ".env").write_text("OCM_SECRET_KEY=very-secret\n")
    (root / "deploy" / ".env").chmod(0o600)
    return BackupPaths(root=root, backup_dir=tmp_path / "backups", key_file=tmp_path / "key")


def run(argv, runner, paths, answers=(), **kwargs):  # type: ignore[no-untyped-def]
    said: list[str] = []
    prompter = ScriptedPrompter(list(answers))
    code = ocm.main(
        argv,
        runner=runner,
        prompter=prompter,
        paths=paths,
        now=lambda: NOW,
        out=said.append,
        **kwargs,
    )
    return code, "\n".join(said), prompter


def git_clean(runner: FakeRunner, *, head="aaa", upstream="bbb", ff=True, branch="main") -> None:
    runner.on("git status --porcelain", Result(0, ""), first=True)
    runner.on("git rev-parse --abbrev-ref", Result(0, branch + "\n"), first=True)
    runner.on("git rev-parse HEAD", Result(0, head + "\n"), first=True)
    runner.on("git rev-parse @{u}", Result(0, upstream + "\n"), first=True)
    runner.on("merge-base --is-ancestor", Result(0 if ff else 1), first=True)


def names(runner: FakeRunner) -> str:
    return "\n".join(runner.joined())


def test_unknown_command_prints_usage(paths: BackupPaths) -> None:
    code, out, _ = run(["frobnicate"], FakeRunner(), paths)
    assert code == 2
    assert "Использование: ocm" in out


def test_no_command_prints_usage_and_succeeds(paths: BackupPaths) -> None:
    code, out, _ = run([], FakeRunner(), paths)
    assert code == 0
    assert "update" in out


def test_status_runs_doctor_and_returns_its_code(paths: BackupPaths) -> None:
    runner = FakeRunner()
    runner.on("doctor.sh", Result(1, "FAIL backup\n"))
    code, out, _ = run(["status"], runner, paths)
    assert code == 1
    assert "FAIL backup" in out


def test_logs_exec_compose_logs_with_the_service(
    paths: BackupPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(paths.root)
    seen: list[list[str]] = []
    code, _, _ = run(["logs", "worker", "-f"], FakeRunner(), paths, exec_fn=seen.append)
    assert code == 0
    assert seen == [["docker", "compose", "logs", "--tail", "200", "-f", "worker"]]


# --- update ---


def test_update_refuses_when_the_clone_has_local_changes(paths: BackupPaths) -> None:
    runner = FakeRunner()
    runner.on("git status --porcelain", Result(0, " M deploy/docker-compose.yml\n"), first=True)
    code, out, _ = run(["update"], runner, paths)
    assert code == 1
    assert "локальные изменения" in out
    text = names(runner)
    assert "build" not in text and "pull" not in text and "pg_dump" not in text


def test_update_refuses_when_not_fast_forward(paths: BackupPaths) -> None:
    runner = FakeRunner()
    git_clean(runner, ff=False)
    code, out, _ = run(["update"], runner, paths)
    assert code == 1
    assert "без слияния" in out
    text = names(runner)
    assert "pull" not in text and "build" not in text and "pg_dump" not in text


def test_update_refuses_on_a_detached_head(paths: BackupPaths) -> None:
    runner = FakeRunner()
    git_clean(runner, branch="HEAD")
    code, out, _ = run(["update"], runner, paths)
    assert code == 1
    assert "git switch" in out
    assert "pull" not in names(runner)


def test_update_does_nothing_when_already_current(paths: BackupPaths) -> None:
    runner = FakeRunner()
    git_clean(runner, head="same", upstream="same")
    code, out, _ = run(["update"], runner, paths)
    assert code == 0
    assert "последняя версия" in out
    assert "pull" not in names(runner)


@requires_openssl
def test_update_runs_backup_before_pulling_and_records_the_previous_revision(
    paths: BackupPaths,
) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    git_clean(stack)
    stack.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, out, _ = run(["update"], stack, paths)
    assert code == 0, out
    calls = stack.joined()
    dump = next(i for i, c in enumerate(calls) if "pg_dump" in c)
    pull = next(i for i, c in enumerate(calls) if c.startswith("git pull --ff-only"))
    build = next(i for i, c in enumerate(calls) if c.endswith("compose build"))
    up = next(i for i, c in enumerate(calls) if c.endswith("compose up -d"))
    assert dump < pull < build < up
    record = json.loads((paths.deploy / ".previous-rev").read_text())
    assert record["rev"] == "aaa"
    assert record["branch"] == "main"
    assert Path(record["backup"]).exists()


def test_update_stops_without_side_effects_if_backup_fails(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    runner = FakeRunner()
    git_clean(runner)
    runner.on("pg_dump", CommandError(["pg_dump"], 1, "connection refused"))
    code, out, _ = run(["update"], runner, paths)
    assert code == 1
    assert "обновление остановлено" in out
    text = names(runner)
    assert "pull" not in text and "build" not in text
    assert not (paths.deploy / ".previous-rev").exists()


@requires_openssl
def test_doctor_failure_after_update_prints_the_rollback_hint_and_exits_nonzero(
    paths: BackupPaths,
) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    git_clean(stack)
    stack.on("scripts/doctor.sh", Result(1, "FAIL api\n"))
    code, out, _ = run(["update"], stack, paths)
    assert code == 1
    assert "ocm rollback" in out


# --- rollback ---


def record_previous(paths: BackupPaths, saved: Path) -> None:
    (paths.deploy / ".previous-rev").write_text(
        json.dumps({"rev": "a" * 40, "branch": "main", "backup": str(saved)})
    )


def test_rollback_without_a_record_says_so(paths: BackupPaths) -> None:
    runner = FakeRunner()
    code, out, _ = run(["rollback"], runner, paths)
    assert code == 1
    assert "откатывать нечего" in out
    assert "checkout" not in names(runner)


def test_rollback_needs_the_confirmation_word(paths: BackupPaths, tmp_path: Path) -> None:
    record_previous(paths, tmp_path / "x.enc")
    runner = FakeRunner()
    code, _, _ = run(["rollback"], runner, paths, answers=["нет"])
    assert code == 1
    assert "checkout" not in names(runner)


@requires_openssl
def test_rollback_asks_before_restoring_the_database(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    saved = backup.create(paths, stack, NOW)
    record_previous(paths, saved)
    stack.calls.clear()
    stack.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, _, prompter = run(["rollback"], stack, paths, answers=["ДА", False])
    assert code == 0
    assert prompter.asked == ["rollback_confirm", "rollback_restore_db"]
    text = names(stack)
    assert f"git checkout {'a' * 40}" in text
    assert "pg_restore" not in text


@requires_openssl
def test_rollback_restores_the_database_when_asked(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    saved = backup.create(paths, stack, NOW)
    record_previous(paths, saved)
    stack.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, _, _ = run(["rollback"], stack, paths, answers=["ДА", True])
    assert code == 0
    assert "pg_restore" in names(stack)


# --- backup / restore ---


@requires_openssl
def test_backup_success_writes_the_marker_and_prunes(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    paths.backup_dir.mkdir(parents=True)
    for day in range(1, 17):
        old = paths.backup_dir / f"ocmanager-2026-09-{day:02d}-0330.tar.gz.enc"
        old.write_bytes(b"x")
    stack = Stack(paths)
    code, out, _ = run(["backup"], stack, paths)
    assert code == 0, out
    assert backup.age_hours(paths.backup_dir, NOW + timedelta(hours=1)) == pytest.approx(1)
    assert len(list(paths.backup_dir.glob("ocmanager-*.enc"))) == backup.KEEP


@requires_openssl
def test_backup_failure_queues_an_admin_alert_and_exits_1(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    stack.on("pg_dump", CommandError(["pg_dump"], 1, "the database system is shut down"))
    code, out, _ = run(["backup"], stack, paths)
    assert code == 1
    alert = next(c for c in stack.joined() if "notify backup-failed" in c)
    assert "--reason" in alert
    assert not (paths.backup_dir / backup.MARKER).exists()


@requires_openssl
def test_backup_failure_keeps_old_copies(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    paths.backup_dir.mkdir(parents=True)
    old = paths.backup_dir / "ocmanager-2026-09-01-0330.tar.gz.enc"
    old.write_bytes(b"x")
    stack = Stack(paths)
    stack.on("pg_dump", CommandError(["pg_dump"], 1, "boom"))
    run(["backup"], stack, paths)
    assert old.exists()


@requires_openssl
def test_a_failing_alert_does_not_hide_the_backup_error(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    stack.on("notify backup-failed", CommandError(["x"], 1, "db down"))
    stack.on("pg_dump", CommandError(["pg_dump"], 1, "db down"))
    code, out, _ = run(["backup"], stack, paths)
    assert code == 1
    assert "Алерт админу не поставлен" in out


@requires_openssl
def test_backup_goes_offsite_when_configured(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    (paths.deploy / ".install-state").write_text(
        json.dumps({"done": [], "answers": {"backup_remote": "me@host.example:/srv/b"}})
    )
    stack = Stack(paths)
    code, _, _ = run(["backup"], stack, paths)
    assert code == 0
    assert any(
        c.startswith("rsync ") and c.endswith("me@host.example:/srv/b") for c in stack.joined()
    )


@requires_openssl
def test_offsite_failure_alerts_but_keeps_the_local_copy(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    (paths.deploy / ".install-state").write_text(
        json.dumps({"done": [], "answers": {"backup_remote": "me@host.example:/srv/b"}})
    )
    stack = Stack(paths)
    stack.on("rsync", CommandError(["rsync"], 255, "unreachable"))
    code, _, _ = run(["backup"], stack, paths)
    assert code == 1
    assert len(list(paths.backup_dir.glob("ocmanager-*.enc"))) == 1
    assert any("notify backup-failed" in c for c in stack.joined())


@requires_openssl
def test_restore_requires_typing_the_confirmation_word(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    saved = backup.create(paths, stack, NOW)
    stack.calls.clear()
    code, out, _ = run(["restore", str(saved)], stack, paths, answers=["да"])
    assert code == 1
    assert "Отменено" in out
    assert "stop" not in names(stack)


@requires_openssl
def test_restore_with_the_word_restores_and_runs_doctor(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    stack = Stack(paths)
    saved = backup.create(paths, stack, NOW)
    stack.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, out, _ = run(["restore", str(saved)], stack, paths, answers=["ДА"])
    assert code == 0, out
    assert "pg_restore" in names(stack)


@requires_openssl
def test_restore_of_a_corrupt_file_is_refused_before_asking(paths: BackupPaths) -> None:
    backup.ensure_key(paths.key_file)
    junk = paths.root / "junk.enc"
    junk.write_bytes(b"not an archive")
    stack = Stack(paths)
    code, out, prompter = run(["restore", str(junk)], stack, paths)
    assert code == 1
    assert prompter.asked == []
    assert "stop" not in names(stack)


def test_restore_without_a_file_prints_usage(paths: BackupPaths) -> None:
    code, out, _ = run(["restore"], FakeRunner(), paths)
    assert code == 2


# --- admin ---


def test_admin_password_goes_through_stdin_not_argv(paths: BackupPaths) -> None:
    runner = FakeRunner()
    secret = "correct horse battery"
    code, _, _ = run(["admin-password", "owner"], runner, paths, answers=[secret])
    assert code == 0
    assert all(secret not in " ".join(c) for c in runner.calls)
    call = next(c for c in runner.joined() if "admin passwd owner" in c)
    assert "--password-stdin" in call
    assert runner.inputs[runner.joined().index(call)] == secret + "\n"


def test_admin_chat_passes_the_id(paths: BackupPaths) -> None:
    runner = FakeRunner()
    runner.on("settings admin-chat", Result(0, "добавлен\n"))
    code, _, _ = run(["admin-chat", "123456"], runner, paths)
    assert code == 0
    assert "settings admin-chat 123456" in names(runner)


def test_admin_chat_rejects_a_non_number(paths: BackupPaths) -> None:
    runner = FakeRunner()
    code, _, _ = run(["admin-chat", "@bob"], runner, paths)
    assert code == 2
    assert runner.calls == []


def test_backup_without_a_key_says_how_to_enable_and_sends_no_alert(paths: BackupPaths) -> None:
    runner = FakeRunner()
    code, out, _ = run(["backup"], runner, paths)
    assert code == 1
    assert "backup-enable" in out
    assert "notify backup-failed" not in names(runner)


def test_backup_enable_creates_the_key_and_the_timer(paths: BackupPaths, tmp_path: Path) -> None:
    runner = FakeRunner()
    code, out, _ = run(["backup-enable"], runner, paths, answers=[""], unit_dir=tmp_path / "units")
    assert code == 0
    assert paths.key_file.exists()
    assert "enable --now ocm-backup.timer" in names(runner)
    assert "КЛЮЧ ШИФРОВАНИЯ" in out


def test_update_without_backups_asks_before_going_ahead(paths: BackupPaths) -> None:
    runner = FakeRunner()
    git_clean(runner)
    code, out, prompter = run(["update"], runner, paths, answers=[False])
    assert code == 1
    assert prompter.asked == ["update_without_backup"]
    assert "pull" not in names(runner)


def test_update_without_backups_can_proceed_when_confirmed(paths: BackupPaths) -> None:
    runner = FakeRunner()
    git_clean(runner)
    runner.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, _, _ = run(["update"], runner, paths, answers=[True])
    assert code == 0
    record = json.loads((paths.deploy / ".previous-rev").read_text())
    assert record["backup"] == ""


def test_rollback_without_a_saved_backup_does_not_offer_a_restore(paths: BackupPaths) -> None:
    (paths.deploy / ".previous-rev").write_text(
        json.dumps({"rev": "a" * 40, "branch": "main", "backup": ""})
    )
    runner = FakeRunner()
    runner.on("scripts/doctor.sh", Result(0, "OK\n"))
    code, _, prompter = run(["rollback"], runner, paths, answers=["ДА"])
    assert code == 0
    assert prompter.asked == ["rollback_confirm"]
