from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from typer.testing import CliRunner

from ocmanager.cli import app

runner = CliRunner()


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    pki, state = tmp_path / "pki", tmp_path / "state"
    monkeypatch.setenv("OCM_PKI_DIR", str(pki))
    monkeypatch.setenv("OCM_OCSERV_STATE_DIR", str(state))
    return pki, state


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_init_creates_ca_and_node_files(dirs: tuple[Path, Path]) -> None:
    pki, state = dirs
    result = runner.invoke(app, ["pki", "init"])
    assert result.exit_code == 0, result.output
    assert mode(pki / "ca.key") == 0o600
    assert mode(pki / "ca.crt") == 0o644
    assert (state / "ca.crt").read_bytes() == (pki / "ca.crt").read_bytes()
    assert not (state / "ca.key").exists()
    crl = x509.load_pem_x509_crl((state / "crl.pem").read_bytes())
    assert len(list(crl)) == 0  # пустой CRL: объект CRL «ложный», проверяем длину
    assert (state / "allowed.list").read_bytes() == b""


def test_second_init_refuses_and_keeps_files(dirs: tuple[Path, Path]) -> None:
    pki, _ = dirs
    runner.invoke(app, ["pki", "init"])
    before = (pki / "ca.key").read_bytes()
    result = runner.invoke(app, ["pki", "init"])
    assert result.exit_code == 1
    assert "CA уже существует" in result.output
    assert (pki / "ca.key").read_bytes() == before


def test_issue_test_cert_prints_working_password(dirs: tuple[Path, Path], tmp_path: Path) -> None:
    runner.invoke(app, ["pki", "init"])
    out = tmp_path / "c9001-d1.p12"
    result = runner.invoke(app, ["pki", "issue-test-cert", "c9001-d1", "--out", str(out)])
    assert result.exit_code == 0, result.output
    password = result.output.split("password:")[1].split()[0]
    _key, cert, _extra = pkcs12.load_key_and_certificates(out.read_bytes(), password.encode())
    assert cert is not None
    assert str(cert.serial_number) in result.output
    assert mode(out) == 0o600


def test_issue_test_cert_rejects_bad_cn(dirs: tuple[Path, Path], tmp_path: Path) -> None:
    runner.invoke(app, ["pki", "init"])
    result = runner.invoke(app, ["pki", "issue-test-cert", "admin", "--out", str(tmp_path / "x")])
    assert result.exit_code == 1


def test_dev_server_cert_goes_to_node_dir(dirs: tuple[Path, Path]) -> None:
    _, state = dirs
    runner.invoke(app, ["pki", "init"])
    result = runner.invoke(app, ["pki", "dev-server-cert", "--host", "ocserv"])
    assert result.exit_code == 0, result.output
    assert mode(state / "server.key") == 0o600
    assert (state / "server.crt").exists()


@pytest.mark.parametrize(
    "args",
    [["dev-server-cert", "--host", "x"], ["issue-test-cert", "c1-d1", "--out", "x"]],
)
def test_dev_commands_refused_in_production(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    runner.invoke(app, ["pki", "init"])
    monkeypatch.setenv("OCM_ENV", "production")
    result = runner.invoke(app, ["pki", *args])
    assert result.exit_code == 1
    assert "только для dev" in result.output
