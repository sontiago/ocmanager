from datetime import UTC
from pathlib import Path

import pytest

from ocmanager.nodes.occtl.parser import OcctlParseError, parse_status, parse_users

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_users_one() -> None:
    [s] = parse_users(load("users_one.json"))
    assert s.username == "c9001-d1"
    assert s.session_id.isdigit()
    assert s.vpn_ip is not None
    assert s.vpn_ip.startswith("10.77.0.")
    assert s.bytes_in > 0
    assert s.bytes_out > 0
    assert s.connected_at.tzinfo is UTC
    assert s.connected_at.year >= 2026
    assert s.user_agent is not None


def test_users_empty() -> None:
    assert parse_users(load("users_empty.json")) == []


def test_users_two_distinct() -> None:
    sessions = parse_users(load("users_two.json"))
    assert {s.username for s in sessions} == {"c9001-d1", "c9001-d2"}
    assert len({s.session_id for s in sessions}) == 2


def test_a_session_still_in_pre_auth_is_not_a_session_yet() -> None:
    # Так occtl показывает подключающегося клиента до конца авторизации: без username и
    # счётчиков. Вылетел в CI, пока клиент ещё подключался (OcctlParseError: 'RX').
    text = (
        '[{"ID": 46, "Username": "(none)", "Groupname": "(none)", "State": "pre-auth",'
        ' "Remote IP": "172.18.0.3"},'
        ' {"ID": 47, "Username": "c1-d1", "State": "connected", "Remote IP": "1.2.3.4",'
        ' "RX": "10", "TX": "20", "raw_connected_at": 1790000000}]'
    )
    assert [s.username for s in parse_users(text)] == ["c1-d1"]


def test_only_pre_auth_sessions_means_nobody_is_online() -> None:
    text = '[{"ID": 46, "Username": "(none)", "State": "pre-auth", "Remote IP": "172.18.0.3"}]'
    assert parse_users(text) == []


def test_a_connected_session_without_counters_is_still_an_error() -> None:
    text = '[{"ID": 5, "Username": "c1-d1", "State": "connected", "Remote IP": "1.2.3.4"}]'
    with pytest.raises(OcctlParseError, match="RX"):
        parse_users(text)


def test_status() -> None:
    st = parse_status(load("status.json"))
    assert st.up is True
    assert st.uptime_s > 0
    assert st.active_sessions == 1
    assert st.raw["Status"] == "online"


def test_rx_string_counter_is_parsed() -> None:
    text = (
        '[{"ID": 5, "Username": "c1-d1", "Remote IP": "1.2.3.4", "RX": "10", "TX": 20,'
        ' "raw_connected_at": 1790000000}]'
    )
    [s] = parse_users(text)
    assert (s.bytes_in, s.bytes_out, s.vpn_ip, s.user_agent) == (10, 20, None, None)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("", "invalid json"),
        ("not json", "invalid json"),
        ("{}", "expected array"),
        ("[1]", "expected object"),
        ('[{"Username": 1}]', "'ID'"),
        (
            '[{"ID": 1, "Username": "c1-d1", "Remote IP": "1.2.3.4", "RX": "1 KB", "TX": "0",'
            ' "raw_connected_at": 1}]',
            "'RX'",
        ),
        (
            '[{"ID": true, "Username": "c1-d1"}]',
            "'ID'",
        ),
    ],
)
def test_garbage_raises_parse_error(text: str, key: str) -> None:
    with pytest.raises(OcctlParseError, match=key):
        parse_users(text)


def test_status_garbage() -> None:
    with pytest.raises(OcctlParseError, match="'Status'"):
        parse_status('{"uptime": 1}')
