"""Чистые правила рефералов и уровней — без БД, времени и сети."""

import secrets
from dataclasses import dataclass
from typing import Final

# Без похожих символов (0/o, 1/l/i): код пересказывают голосом и вводят руками.
_ALPHABET: Final = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_LENGTH: Final = 8
START_PREFIX: Final = "ref_"

# Награда за первого платящего друга и потолок базовых наград пригласившему за 30 суток.
INVITEE_DAYS: Final = 3
INVITER_DAYS: Final = 7
MONTHLY_CAP: Final = 10
GIB: Final = 1024**3


@dataclass(frozen=True)
class Tier:
    friends: int  # сколько платящих друзей нужно
    days: int = 0
    devices: int = 0
    traffic_bytes: int = 0
    badge: str | None = None


TIERS: Final = (
    Tier(friends=3, days=30, badge="friend"),
    Tier(friends=5, devices=1),
    Tier(friends=10, traffic_bytes=100 * GIB, badge="ambassador"),
)


def new_referral_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))


def parse_start_param(param: str | None) -> str | None:
    """`ref_ab12cd34` → `ab12cd34`; всё остальное (пусто, чужой формат) → None."""
    if not param or not param.startswith(START_PREFIX):
        return None
    code = param.removeprefix(START_PREFIX).lower()
    if len(code) != CODE_LENGTH or any(ch not in _ALPHABET for ch in code):
        return None
    return code


def tiers_reached(paying_friends: int) -> list[Tier]:
    return [t for t in TIERS if paying_friends >= t.friends]


def next_tier(paying_friends: int) -> Tier | None:
    return next((t for t in TIERS if paying_friends < t.friends), None)


def badges(paying_friends: int) -> list[str]:
    return [t.badge for t in tiers_reached(paying_friends) if t.badge is not None]
