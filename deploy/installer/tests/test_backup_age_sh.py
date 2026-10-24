import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib-backup-age.sh"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None
    or subprocess.run(["date", "-d", "now"], capture_output=True).returncode != 0,
    reason="нужен GNU date (Linux)",
)


def fresh(marker: Path) -> int:
    cmd = f'. "{LIB}"; backup_is_fresh "{marker}" {int(NOW.timestamp())}'
    return subprocess.run(["bash", "-c", cmd]).returncode


def mark(tmp_path: Path, hours: float) -> Path:
    marker = tmp_path / "last-ok"
    marker.write_text((NOW - timedelta(hours=hours)).isoformat() + "\n")
    return marker


def test_no_marker_is_stale(tmp_path: Path) -> None:
    assert fresh(tmp_path / "missing") == 1


def test_35_hours_is_fresh(tmp_path: Path) -> None:
    assert fresh(mark(tmp_path, 35)) == 0


def test_37_hours_is_stale(tmp_path: Path) -> None:
    assert fresh(mark(tmp_path, 37)) == 1
