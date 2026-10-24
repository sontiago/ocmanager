from pathlib import Path

from installer import systemd
from installer.runner import FakeRunner


def test_the_units_have_the_agreed_schedule_and_command(tmp_path: Path) -> None:
    timer = systemd.render_timer()
    service = systemd.render_service(tmp_path)
    assert "OnCalendar=*-*-* 03:30:00" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300" in timer
    assert f"WorkingDirectory={tmp_path}" in service
    assert "ExecStart=/usr/local/bin/ocm backup" in service
    assert "Type=oneshot" in service


def test_install_writes_both_units_and_enables_the_timer(tmp_path: Path) -> None:
    runner = FakeRunner()
    units = tmp_path / "units"
    systemd.install(runner, tmp_path, unit_dir=units)
    assert (units / systemd.SERVICE).exists()
    assert (units / systemd.TIMER).exists()
    assert runner.joined() == [
        "systemctl daemon-reload",
        "systemctl enable --now ocm-backup.timer",
    ]


def test_install_twice_does_not_fail(tmp_path: Path) -> None:
    runner = FakeRunner()
    units = tmp_path / "units"
    systemd.install(runner, tmp_path, unit_dir=units)
    first = (units / systemd.TIMER).read_text()
    systemd.install(runner, tmp_path, unit_dir=units)
    assert (units / systemd.TIMER).read_text() == first


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    runner = FakeRunner()
    units = tmp_path / "units"
    systemd.install(runner, tmp_path, unit_dir=units, dry_run=True)
    assert not units.exists()
    assert runner.calls == []


def test_uninstall_removes_the_units(tmp_path: Path) -> None:
    runner = FakeRunner()
    units = tmp_path / "units"
    systemd.install(runner, tmp_path, unit_dir=units)
    systemd.uninstall(runner, unit_dir=units)
    assert not (units / systemd.TIMER).exists()
    assert not (units / systemd.SERVICE).exists()
