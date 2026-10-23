import pytest

from ocmanager.subscriptions import referral
from ocmanager.subscriptions.referral import (
    CODE_LENGTH,
    GIB,
    badges,
    new_referral_code,
    next_tier,
    parse_start_param,
    tiers_reached,
)


def test_codes_have_the_agreed_length_and_alphabet() -> None:
    for _ in range(200):
        code = new_referral_code()
        assert len(code) == CODE_LENGTH
        assert not set(code) & set("0o1li")  # символы, которые путают при пересказе


def test_codes_are_not_repeated_in_a_small_sample() -> None:
    assert len({new_referral_code() for _ in range(1000)}) == 1000


@pytest.mark.parametrize(
    ("param", "code"),
    [
        ("ref_ab23cd45", "ab23cd45"),
        ("ref_AB23CD45", "ab23cd45"),  # регистр не важен: ссылку могут набрать руками
    ],
)
def test_a_valid_start_param_gives_the_code(param: str, code: str) -> None:
    assert parse_start_param(param) == code


@pytest.mark.parametrize(
    "param",
    [None, "", "ref_", "ref_short", "ref_ab23cd456", "xyz_ab23cd45", "ref_ab0lcd45", "ab23cd45"],
)
def test_anything_else_is_ignored(param: str | None) -> None:
    assert parse_start_param(param) is None


@pytest.mark.parametrize(
    ("friends", "expected"),
    [
        (0, []),
        (2, []),
        (3, [3]),
        (4, [3]),
        (5, [3, 5]),
        (9, [3, 5]),
        (10, [3, 5, 10]),
        (50, [3, 5, 10]),
    ],
)
def test_tiers_are_cumulative(friends: int, expected: list[int]) -> None:
    assert [t.friends for t in tiers_reached(friends)] == expected


@pytest.mark.parametrize(
    ("friends", "expected"), [(0, 3), (2, 3), (3, 5), (5, 10), (9, 10), (10, None)]
)
def test_next_tier(friends: int, expected: int | None) -> None:
    tier = next_tier(friends)
    assert (tier.friends if tier else None) == expected


def test_badges_follow_the_tiers() -> None:
    assert badges(2) == []
    assert badges(3) == ["friend"]
    assert badges(5) == ["friend"]
    assert badges(10) == ["friend", "ambassador"]


def test_the_agreed_rewards() -> None:
    assert (referral.INVITEE_DAYS, referral.INVITER_DAYS, referral.MONTHLY_CAP) == (3, 7, 10)
    by_friends = {t.friends: t for t in referral.TIERS}
    assert by_friends[3].days == 30
    assert by_friends[5].devices == 1
    assert by_friends[10].traffic_bytes == 100 * GIB
