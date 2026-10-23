from pathlib import Path

import pytest

from installer.runner import FakeNet, FakeRunner


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def net() -> FakeNet:
    return FakeNet(public_ip="203.0.113.10")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Копия каталога установки: deploy/.env.example нужен для render_env."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    example = Path(__file__).resolve().parents[2] / ".env.example"
    (deploy / ".env.example").write_text(example.read_text())
    return tmp_path
