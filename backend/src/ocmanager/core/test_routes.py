import pytest

from ocmanager.core.routes import normalize_route, normalize_routes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("85.142.247.47", "85.142.247.47/32"),
        (" 178.176.128.202/32 ", "178.176.128.202/32"),
        ("10.1.2.3/8", "10.0.0.0/8"),
        ("192.168.0.0/16", "192.168.0.0/16"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize_route(raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "1.2.3", "1.2.3.4/33", "256.1.1.1", "::1", "2001:db8::/32", "0.0.0.0/0",
     "127.0.0.1", "224.0.0.1", "169.254.1.1", "1.2.3.4; no-route = 0.0.0.0/0", "1.2.3.4\nroute"],
)  # fmt: skip
def test_rejects(bad: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 — текст зависит от причины
        normalize_route(bad)


def test_normalize_routes_dedupes_and_sorts_numerically() -> None:
    assert normalize_routes(["10.0.0.9", "9.9.9.9/32", "10.0.0.9/32"]) == [
        "9.9.9.9/32",
        "10.0.0.9/32",
    ]
