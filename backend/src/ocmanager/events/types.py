"""Доменные события — контракт между модулями.

Payload — только id и скаляры: обработчик сам читает актуальное состояние
из БД. Событие доставляется at-least-once, поэтому каждый обработчик обязан
быть идемпотентным. Имя события — ключ в event_outbox: не переименовывать
без миграции данных.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: ClassVar[str]
    registry: ClassVar[dict[str, type["DomainEvent"]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        name = cls.__dict__.get("name")
        if not isinstance(name, str):
            raise TypeError(f"{cls.__name__} must define name: ClassVar[str]")
        if name in DomainEvent.registry:
            raise TypeError(f"duplicate event name {name!r}")
        DomainEvent.registry[name] = cls


def parse_event(name: str, payload: dict[str, Any]) -> DomainEvent:
    try:
        cls = DomainEvent.registry[name]
    except KeyError:
        raise ValueError(f"unknown event {name!r}") from None
    return cls.model_validate(payload)


class SubscriptionActivated(DomainEvent):
    name: ClassVar[str] = "subscription.activated"
    client_id: int


class SubscriptionRenewed(DomainEvent):
    name: ClassVar[str] = "subscription.renewed"
    client_id: int


class SubscriptionAutoRenewCancelled(DomainEvent):
    name: ClassVar[str] = "subscription.auto_renew_cancelled"
    client_id: int


class SubscriptionExpired(DomainEvent):
    name: ClassVar[str] = "subscription.expired"
    client_id: int


class ClientBlocked(DomainEvent):
    name: ClassVar[str] = "client.blocked"
    client_id: int


class ClientUnblocked(DomainEvent):
    name: ClassVar[str] = "client.unblocked"
    client_id: int


class DeviceIssued(DomainEvent):
    name: ClassVar[str] = "device.issued"
    client_id: int
    device_id: int


class DeviceRevoked(DomainEvent):
    name: ClassVar[str] = "device.revoked"
    client_id: int
    device_id: int
    username: str


class NodeStatusChanged(DomainEvent):
    name: ClassVar[str] = "node.status_changed"
    node_id: int
    old: str
    new: str


class PaymentReceived(DomainEvent):
    name: ClassVar[str] = "payment.received"
    payment_id: int
    client_id: int


class PaymentRefunded(DomainEvent):
    name: ClassVar[str] = "payment.refunded"
    payment_id: int
    client_id: int


class PaymentNeedsReview(DomainEvent):
    name: ClassVar[str] = "payment.needs_review"
    payment_id: int
    client_id: int


class WebhookDeadLettered(DomainEvent):
    name: ClassVar[str] = "webhook.dead_lettered"
    webhook_event_id: int


class WebhookRejected(DomainEvent):
    """Вебхук с неверной подписью."""

    name: ClassVar[str] = "webhook.rejected"
    webhook_event_id: int
