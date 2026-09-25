from datetime import UTC, datetime


def utcnow() -> datetime:
    """Единственный источник «сейчас» в коде. В тестах подменяется time-machine."""
    return datetime.now(UTC)
