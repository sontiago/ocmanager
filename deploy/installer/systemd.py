"""Расписание резервных копий: systemd-таймер раз в сутки в 03:30."""

from pathlib import Path

from installer.runner import Runner

UNIT_DIR = Path("/etc/systemd/system")
SERVICE = "ocm-backup.service"
TIMER = "ocm-backup.timer"
OCM_LINK = Path("/usr/local/bin/ocm")


def render_service(install_dir: Path, ocm: Path = OCM_LINK) -> str:
    return (
        "[Unit]\n"
        "Description=Резервная копия ocmanager\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={install_dir}\n"
        f"ExecStart={ocm} backup\n"
    )


def render_timer() -> str:
    return (
        "[Unit]\n"
        "Description=Ежедневная резервная копия ocmanager\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=*-*-* 03:30:00\n"
        "Persistent=true\n"
        "RandomizedDelaySec=300\n"
        f"Unit={SERVICE}\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def install(
    runner: Runner,
    install_dir: Path,
    *,
    unit_dir: Path = UNIT_DIR,
    ocm: Path = OCM_LINK,
    dry_run: bool = False,
) -> None:
    """Пишет оба юнита и включает таймер. Повторный вызов безопасен: файлы перезаписываются
    тем же содержимым, `enable --now` на включённом таймере ничего не ломает."""
    if dry_run:
        return
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / SERVICE).write_text(render_service(install_dir.resolve(), ocm))
    (unit_dir / TIMER).write_text(render_timer())
    runner.run(["systemctl", "daemon-reload"])
    runner.run(["systemctl", "enable", "--now", TIMER])


def uninstall(runner: Runner, *, unit_dir: Path = UNIT_DIR) -> None:
    runner.run(["systemctl", "disable", "--now", TIMER], check=False)
    for name in (TIMER, SERVICE):
        (unit_dir / name).unlink(missing_ok=True)
    runner.run(["systemctl", "daemon-reload"], check=False)
