import os
import stat
from pathlib import Path

import pytest

from installer import config


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://App.Example.com/ ", "app.example.com"),
        ("  vpn.example.org. ", "vpn.example.org"),
        ("http://a.b.co/path/", "a.b.co"),
        ("sub.domain.example.com", "sub.domain.example.com"),
    ],
)
def test_normalize_domain_cleans_what_people_paste(raw: str, expected: str) -> None:
    assert config.normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.2.3.4",
        "app.example.com:8080",
        "",
        "   ",
        "localhost",
        "бот.рф",
        "a_b.example.com",
        "-a.example.com",
        "a..com",
    ],
)
def test_normalize_domain_refuses_what_caddy_cannot_certify(raw: str) -> None:
    with pytest.raises(ValueError):
        config.normalize_domain(raw)


def test_the_two_domains_must_differ() -> None:
    with pytest.raises(ValueError, match="разными"):
        config.validate_distinct_domains("a.example.com", "a.example.com")
    config.validate_distinct_domains("a.example.com", "b.example.com")


@pytest.mark.parametrize("good", ["me@example.com", "a.b+c@sub.example.org"])
def test_validate_email_accepts_normal_addresses(good: str) -> None:
    assert config.validate_email(good) == good


@pytest.mark.parametrize("bad", ["", "no-at.example.com", "a@b", "a @b.com", "@b.com"])
def test_validate_email_refuses_the_rest(bad: str) -> None:
    with pytest.raises(ValueError):
        config.validate_email(bad)


def test_validate_bot_token() -> None:
    token = "123456789:AAH-abcdefghijklmnopqrstuvwxyz_01"
    assert config.validate_bot_token(f" {token} ") == token
    for bad in ("", "abc", "123456:short", "notanumber:abcdefghijklmnopqrstuvwxyz"):
        with pytest.raises(ValueError):
            config.validate_bot_token(bad)


def test_validate_admin_password_length_rules() -> None:
    assert config.validate_admin_password("a" * 12) == "a" * 12
    with pytest.raises(ValueError, match="12"):
        config.validate_admin_password("a" * 11)
    with pytest.raises(ValueError, match="72"):
        config.validate_admin_password("я" * 37)  # 74 байта


def test_validate_admin_username() -> None:
    assert config.validate_admin_username("owner") == "owner"
    for bad in ("ab", "x" * 33, "Owner", "with space", "a@b"):
        with pytest.raises(ValueError):
            config.validate_admin_username(bad)


def test_generated_password_passes_the_password_rule() -> None:
    config.validate_admin_password(config.generate_password())


def test_generate_secrets_shapes_and_uniqueness() -> None:
    a, b = config.generate_secrets(), config.generate_secrets()
    assert set(a) == {
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "OCM_SECRET_KEY",
        "OCM_INTERNAL_TOKEN",
        "OCM_CAMOUFLAGE_SECRET",
    }
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        assert len(a[key]) == 48
        int(a[key], 16)  # только hex: пароль идёт в URL
    assert len(a["OCM_SECRET_KEY"]) >= 32
    assert len(a["OCM_INTERNAL_TOKEN"]) >= 32
    assert len(a["OCM_CAMOUFLAGE_SECRET"]) >= 4
    assert all(a[k] != b[k] for k in a)


VALUES = {
    "DOMAIN_APP": "app.example.com",
    "DOMAIN_VPN": "vpn.example.com",
    "ACME_EMAIL": "me@example.com",
    "POSTGRES_PASSWORD": "a" * 48,
    "REDIS_PASSWORD": "b" * 48,
    "OCM_SECRET_KEY": "k" * 64,
    "OCM_INTERNAL_TOKEN": "t" * 64,
    "OCM_CAMOUFLAGE_SECRET": "camo-secret",
    "OCM_BOT_TOKEN": "123456789:AAH-abcdefghijklmnopqrstuvwxyz_01",
    "OCM_BOT_USERNAME": "ocbot",
    "OCM_TRIBUTE_API_KEY": "",
}


def test_render_then_parse_is_the_identity(root: Path) -> None:
    text = config.render_env(VALUES, root / "deploy" / ".env.example")
    parsed = config.parse_env(text)
    assert {k: parsed[k] for k in VALUES} == VALUES


def test_render_env_keeps_every_key_of_the_example_so_they_never_drift(root: Path) -> None:
    example = (root / "deploy" / ".env.example").read_text()
    wanted = set(config.parse_env(example))
    rendered = set(config.parse_env(config.render_env(VALUES, root / "deploy" / ".env.example")))
    assert wanted <= rendered


def test_render_env_refuses_a_value_that_is_not_in_the_example(root: Path) -> None:
    with pytest.raises(KeyError, match="NO_SUCH_KEY"):
        config.render_env({**VALUES, "NO_SUCH_KEY": "x"}, root / "deploy" / ".env.example")


def test_render_env_keeps_the_comments_of_the_example(root: Path) -> None:
    text = config.render_env(VALUES, root / "deploy" / ".env.example")
    assert "# --- Домены" in text


def test_render_env_leaves_example_values_for_keys_we_did_not_set(root: Path) -> None:
    text = config.render_env(VALUES, root / "deploy" / ".env.example")
    assert config.parse_env(text)["OCSERV_IPV4_NETWORK"] == "10.77.0.0/24"


def test_parse_env_ignores_comments_and_blank_lines_and_strips_quotes() -> None:
    parsed = config.parse_env('# c\n\nA=1\nB="two words"\nC=\n')
    assert parsed == {"A": "1", "B": "two words", "C": ""}


def test_write_env_is_0600_and_atomic(root: Path) -> None:
    target = root / "deploy" / ".env"
    config.write_env(target, config.render_env(VALUES, root / "deploy" / ".env.example"))
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list((root / "deploy").glob(".env.tmp*"))


def test_write_env_moves_the_old_file_to_env_bak(root: Path) -> None:
    target = root / "deploy" / ".env"
    target.write_text("OLD=1\n")
    config.write_env(target, "NEW=2\n")
    assert (root / "deploy" / ".env.bak").read_text() == "OLD=1\n"
    assert target.read_text() == "NEW=2\n"


def test_an_interrupted_write_leaves_the_old_env_intact(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = root / "deploy" / ".env"
    target.write_text("OLD=1\n")

    def explode(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        config.write_env(target, "NEW=2\n")
    assert target.read_text() == "OLD=1\n"
    assert not list((root / "deploy").glob(".env.tmp*"))
