from typing import ClassVar

import pytest
from pydantic import ValidationError

from ocmanager.events.types import (
    DeviceRevoked,
    DomainEvent,
    SubscriptionActivated,
    parse_event,
)


def test_every_event_is_registered_by_name() -> None:
    assert DomainEvent.registry["device.revoked"] is DeviceRevoked
    assert len(DomainEvent.registry) == 14


def test_roundtrip_through_json_payload() -> None:
    event = DeviceRevoked(client_id=1, device_id=2, username="c1-d2")
    payload = event.model_dump(mode="json")
    assert parse_event("device.revoked", payload) == event


def test_events_are_immutable() -> None:
    event = SubscriptionActivated(client_id=1)
    with pytest.raises(ValidationError):
        event.client_id = 2  # type: ignore[misc]


def test_unknown_event_name() -> None:
    with pytest.raises(ValueError, match="unknown event"):
        parse_event("nope", {})


def test_payload_is_validated() -> None:
    with pytest.raises(ValidationError):
        parse_event("subscription.activated", {"client_id": "x"})


def test_duplicate_name_rejected() -> None:
    with pytest.raises(TypeError, match="duplicate"):

        class Again(DomainEvent):
            name: ClassVar[str] = "device.revoked"


def test_missing_name_rejected() -> None:
    with pytest.raises(TypeError, match="must define name"):

        class Nameless(DomainEvent):
            x: int
