import os
import stat
import time
from datetime import timedelta
from pathlib import Path

import pytest

from installer import backup
from installer.backup import BackupError, BackupPaths
from installer.runner import CommandError, FakeRunner, Result
from installer.tests.conftest import DUMP_BYTES, NOW, PKI_BYTES, Stack, requires_openssl

pytestmark = requires_openssl


@pytest.fixture
def paths(root: Path, tmp_path: Path) -> BackupPaths:
    (root / "deploy" / ".env").write_text("OCM_SECRET_KEY=very-secret\n")
    (root / "deploy" / ".env").chmod(0o600)
    return BackupPaths(
        root=root,
        backup_dir=tmp_path / "backups",
        key_file=tmp_path / "backup-key",
    )


@pytest.fixture
def stack(paths: BackupPaths) -> Stack:
    backup.ensure_key(paths.key_file)
    return Stack(paths)


def test_the_key_is_created_once_with_0600(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    first = backup.ensure_key(key_file)
    assert len(first) >= 32
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert backup.ensure_key(key_file) == first  # существующий не трогаем


def test_a_key_readable_by_others_is_refused(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    backup.ensure_key(key_file)
    key_file.chmod(0o644)
    with pytest.raises(BackupError, match="права"):
        backup.read_key(key_file)


def test_create_makes_an_encrypted_file_that_is_not_a_plain_archive(
    paths: BackupPaths, stack: Stack
) -> None:
    path = backup.create(paths, stack, NOW)
    assert path.name == "ocmanager-2026-10-23-0330.tar.gz.enc"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    head = path.read_bytes()[:16]
    assert head.startswith(b"Salted__")  # формат openssl enc: открытого tar.gz внутри нет
    assert b"very-secret" not in path.read_bytes()
    assert DUMP_BYTES not in path.read_bytes()


def test_the_roundtrip_returns_the_same_files(
    paths: BackupPaths, stack: Stack, tmp_path: Path
) -> None:
    path = backup.create(paths, stack, NOW)
    manifest = backup.verify(path, paths.key_file, stack)
    assert manifest.format == 1
    assert manifest.version == "abc1234"
    assert manifest.created.startswith("2026-10-23")
    out = tmp_path / "out"
    backup.extract(path, paths.key_file, stack, out)
    assert (out / "db.dump").read_bytes() == DUMP_BYTES
    assert (out / "pki.tgz").read_bytes() == PKI_BYTES
    assert (out / "env").read_text() == "OCM_SECRET_KEY=very-secret\n"


def test_the_dump_is_taken_inside_postgres_and_copied_out(paths: BackupPaths, stack: Stack) -> None:
    backup.create(paths, stack, NOW)
    joined = stack.joined()
    assert any(
        "exec -T postgres pg_dump -U ocm -Fc -f /tmp/ocm.dump ocmanager" in c for c in joined
    )
    assert any("cp postgres:/tmp/ocm.dump" in c for c in joined)
    assert any("exec -T postgres rm -f /tmp/ocm.dump" in c for c in joined)


def test_the_pki_volume_is_read_only_during_backup(paths: BackupPaths, stack: Stack) -> None:
    backup.create(paths, stack, NOW)
    pki = next(c for c in stack.joined() if "alpine tar czf" in c)
    assert "ocmanager_pki:/pki:ro" in pki


def test_intermediate_files_are_removed_even_when_the_dump_fails(
    paths: BackupPaths, stack: Stack
) -> None:
    failing = Stack(paths)
    failing._rules.insert(0, ("pg_dump", CommandError(["pg_dump"], 1, "connection refused")))
    with pytest.raises(BackupError, match="connection refused"):
        backup.create(paths, failing, NOW)
    assert not any(p.name.startswith(".tmp") for p in paths.backup_dir.iterdir())
    assert list(paths.backup_dir.glob("ocmanager-*")) == []


def test_a_failed_backup_leaves_the_old_copies_alone(paths: BackupPaths, stack: Stack) -> None:
    old = backup.create(paths, stack, NOW - timedelta(days=1))
    failing = Stack(paths)
    failing._rules.insert(0, ("pg_dump", CommandError(["pg_dump"], 1, "boom")))
    with pytest.raises(BackupError):
        backup.create(paths, failing, NOW)
    assert old.exists()


def test_the_backup_dir_is_private(paths: BackupPaths, stack: Stack) -> None:
    backup.create(paths, stack, NOW)
    assert stat.S_IMODE(paths.backup_dir.stat().st_mode) == 0o700


def test_a_wrong_key_is_refused_before_anything_is_touched(
    paths: BackupPaths, stack: Stack, tmp_path: Path
) -> None:
    path = backup.create(paths, stack, NOW)
    other = tmp_path / "other-key"
    backup.ensure_key(other)
    runner = Stack(paths)
    with pytest.raises(BackupError, match="ключ"):
        backup.restore(path, BackupPaths(paths.root, paths.backup_dir, other), runner, NOW)
    joined = " ".join(runner.joined())
    assert " stop" not in joined
    assert "DROP" not in joined


def test_a_corrupted_file_is_refused(paths: BackupPaths, stack: Stack) -> None:
    path = backup.create(paths, stack, NOW)
    data = bytearray(path.read_bytes())
    data[40] ^= 0xFF
    data[41] ^= 0xFF
    path.write_bytes(bytes(data))
    runner = Stack(paths)
    with pytest.raises(BackupError):
        backup.restore(path, paths, runner, NOW)
    assert " stop" not in " ".join(runner.joined())


def test_a_file_that_is_not_a_backup_is_refused(
    paths: BackupPaths, stack: Stack, tmp_path: Path
) -> None:
    junk = tmp_path / "junk.enc"
    junk.write_bytes(b"not an encrypted archive at all")
    with pytest.raises(BackupError):
        backup.verify(junk, paths.key_file, stack)


def test_restore_order_is_stop_drop_load_pki_up(paths: BackupPaths, stack: Stack) -> None:
    path = backup.create(paths, stack, NOW)
    runner = Stack(paths)
    backup.restore(path, paths, runner, NOW + timedelta(hours=1))
    joined = runner.joined()
    positions = {
        "stop": next(i for i, c in enumerate(joined) if "compose stop" in c),
        "drop": next(i for i, c in enumerate(joined) if "DROP DATABASE" in c),
        "create": next(i for i, c in enumerate(joined) if "CREATE DATABASE" in c),
        "load": next(i for i, c in enumerate(joined) if "pg_restore" in c),
        "pki": next(i for i, c in enumerate(joined) if "alpine sh -c" in c),
        "up": max(i for i, c in enumerate(joined) if c.endswith("compose up -d")),
    }
    assert positions["stop"] < positions["drop"] < positions["create"] < positions["load"]
    assert positions["load"] < positions["pki"] < positions["up"]
    assert runner.dump_loaded == DUMP_BYTES
    assert runner.pki_restored == PKI_BYTES


def test_restore_stops_the_application_services_but_not_the_database(
    paths: BackupPaths, stack: Stack
) -> None:
    path = backup.create(paths, stack, NOW)
    runner = Stack(paths)
    backup.restore(path, paths, runner, NOW)
    stop = next(c for c in runner.joined() if "compose stop" in c)
    for service in ("api-public", "api-admin", "worker", "bot", "ocserv", "caddy", "nginx"):
        assert service in stop
    assert "postgres" not in stop


def test_restore_takes_an_emergency_backup_first(paths: BackupPaths, stack: Stack) -> None:
    path = backup.create(paths, stack, NOW)
    runner = Stack(paths)
    backup.restore(path, paths, runner, NOW + timedelta(hours=1))
    emergency = list(paths.backup_dir.glob("pre-restore-*.tar.gz.enc"))
    assert len(emergency) == 1
    first_stop = next(i for i, c in enumerate(runner.joined()) if "compose stop" in c)
    first_dump = next(i for i, c in enumerate(runner.joined()) if "pg_dump" in c)
    assert first_dump < first_stop


def test_restore_keeps_env_unless_asked(paths: BackupPaths, stack: Stack) -> None:
    path = backup.create(paths, stack, NOW)
    env = paths.root / "deploy" / ".env"
    env.write_text("OCM_SECRET_KEY=changed-after-backup\n")
    backup.restore(path, paths, Stack(paths), NOW)
    assert env.read_text() == "OCM_SECRET_KEY=changed-after-backup\n"
    backup.restore(path, paths, Stack(paths), NOW, restore_env=True)
    assert env.read_text() == "OCM_SECRET_KEY=very-secret\n"
    assert (paths.root / "deploy" / ".env.pre-restore").read_text() == (
        "OCM_SECRET_KEY=changed-after-backup\n"
    )
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def create_with_names(paths: BackupPaths, names: list[str]) -> None:
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (paths.backup_dir / name).write_bytes(b"x")


def test_prune_keeps_the_newest_14(paths: BackupPaths) -> None:
    names = [f"ocmanager-2026-10-{day:02d}-0330.tar.gz.enc" for day in range(1, 21)]
    create_with_names(paths, names)
    removed = backup.prune(paths.backup_dir, keep=14)
    assert sorted(p.name for p in removed) == names[:6]
    assert sorted(p.name for p in paths.backup_dir.glob("ocmanager-*")) == names[6:]


def test_prune_ignores_foreign_files_and_the_marker(paths: BackupPaths) -> None:
    create_with_names(paths, ["notes.txt", "last-ok", "ocmanager-2026-10-01-0330.tar.gz.enc"])
    assert backup.prune(paths.backup_dir, keep=0) != []
    assert (paths.backup_dir / "notes.txt").exists()
    assert (paths.backup_dir / "last-ok").exists()


def test_prune_does_nothing_when_there_are_few(paths: BackupPaths) -> None:
    create_with_names(paths, ["ocmanager-2026-10-01-0330.tar.gz.enc"])
    assert backup.prune(paths.backup_dir, keep=14) == []


def test_emergency_copies_are_pruned_separately_to_three(paths: BackupPaths) -> None:
    names = [f"pre-restore-2026-10-{day:02d}-0330.tar.gz.enc" for day in range(1, 7)]
    create_with_names(paths, names)
    backup.prune(paths.backup_dir, keep=14)
    assert len(list(paths.backup_dir.glob("pre-restore-*"))) == 3


def test_age_is_unknown_without_a_marker_and_grows_with_time(paths: BackupPaths) -> None:
    assert backup.age_hours(paths.backup_dir, NOW) is None
    paths.backup_dir.mkdir(parents=True)
    backup.record_success(paths.backup_dir, NOW)
    assert backup.age_hours(paths.backup_dir, NOW + timedelta(hours=5)) == pytest.approx(5.0)


def test_an_unreadable_marker_means_unknown_age(paths: BackupPaths) -> None:
    paths.backup_dir.mkdir(parents=True)
    (paths.backup_dir / "last-ok").write_text("garbage")
    assert backup.age_hours(paths.backup_dir, NOW) is None


def test_offsite_uses_rsync_for_a_remote_target() -> None:
    runner = FakeRunner()
    backup.copy_offsite(
        Path("/var/backups/ocmanager/a.enc"), "me@host.example:/srv/backups", runner
    )
    [cmd] = runner.joined()
    assert cmd.startswith("rsync -a -e ssh")
    assert cmd.endswith("/var/backups/ocmanager/a.enc me@host.example:/srv/backups")
    assert "BatchMode=yes" in cmd


def test_offsite_copies_to_a_local_directory_with_cp() -> None:
    runner = FakeRunner()
    backup.copy_offsite(Path("/var/backups/ocmanager/a.enc"), "/mnt/usb", runner)
    assert runner.joined() == ["cp -p /var/backups/ocmanager/a.enc /mnt/usb"]


def test_offsite_failure_is_a_backup_error() -> None:
    runner = FakeRunner()
    runner.on("rsync", Result(23, "", "permission denied"))
    with pytest.raises(BackupError, match="permission denied"):
        backup.copy_offsite(Path("/x.enc"), "me@host:/srv", runner)


def test_extraction_refuses_path_traversal_members(
    paths: BackupPaths, stack: Stack, tmp_path: Path
) -> None:
    import io
    import tarfile

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        data = b"pwned"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        tar.addfile(tarfile.TarInfo("manifest.json"), io.BytesIO(b""))
    enc = tmp_path / "evil.enc"
    stack.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            str(evil),
            "-out",
            str(enc),
            "-pass",
            f"file:{paths.key_file}",
        ]
    )
    with pytest.raises(BackupError):
        backup.extract(enc, paths.key_file, stack, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_timestamps_in_names_sort_chronologically() -> None:
    a = backup.name_for(NOW)
    b = backup.name_for(NOW + timedelta(minutes=1))
    assert a < b
    assert time.strptime(a[len("ocmanager-") : len("ocmanager-") + 15], "%Y-%m-%d-%H%M")
    assert os.sep not in a
