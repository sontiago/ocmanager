from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramIdentity:
    """То, что Telegram сообщает о пользователе (initData → user)."""

    telegram_id: int
    first_name: str
    username: str | None
    language_code: str | None
