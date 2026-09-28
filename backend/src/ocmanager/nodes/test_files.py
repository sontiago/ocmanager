import os
from pathlib import Path

import pytest

from ocmanager.nodes import files
from ocmanager.nodes.driver.contract import make_crl_pem


def test_render_sorted_unique_with_trailing_newline() -> None:
    assert files.render_allowlist(["c2-d1", "c1-d1", "c2-d1"]) == b"c1-d1\nc2-d1\n"


def test_render_empty() -> None:
    assert files.render_allowlist([]) == b""


@pytest.mark.parametrize("bad", ["", "c1-d1\n", "c1-d1\nc2-d2", "../x", "C1-D1", " c1-d1"])
def test_render_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid ocserv username"):
        files.render_allowlist(["c1-d1", bad])


def test_parse_keeps_everything_nonblank() -> None:
    assert files.parse_allowlist(b"c1-d1\n\n  junk  \nc1-d1\n") == {"c1-d1", "junk"}


def test_validate_crl() -> None:
    files.validate_crl(make_crl_pem())
    with pytest.raises(ValueError, match="not a PEM-encoded CRL"):
        files.validate_crl(b"-----BEGIN X509 CRL-----\nAAAA\n-----END X509 CRL-----\n")


def test_atomic_write_replaces_with_mode(tmp_path: Path) -> None:
    target = tmp_path / "allowed.list"
    target.write_bytes(b"old\n")
    files.atomic_write(target, b"new\n", mode=0o640)
    assert target.read_bytes() == b"new\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_failure_keeps_original_and_no_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "crl.pem"
    target.write_bytes(b"original")

    def boom(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        files.atomic_write(target, b"new")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]
