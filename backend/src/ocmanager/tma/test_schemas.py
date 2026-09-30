from datetime import UTC, datetime, timedelta, timezone

from ocmanager.tma import schemas

# Набор полей каждой модели повторяет frontend/tma/src/api/types.ts. Переименование или
# потеря поля ломает этот тест, а не Mini App у клиентов. Меняете поле — правьте types.ts.
FIELDS = {
    "MeOut": {"telegram_id", "first_name", "username", "lang", "is_blocked", "trial_available"},
    "PlanOut": {
        "code",
        "name",
        "description",
        "duration_days",
        "device_limit",
        "traffic_limit_bytes",
        "speed_limit_kbps",
        "price_amount",
        "currency",
        "is_trial",
        "sort_order",
    },
    "SubscriptionOut": {
        "id",
        "plan",
        "status",
        "started_at",
        "expires_at",
        "traffic_used_bytes",
        "traffic_limit_bytes",
        "traffic_period_start",
        "device_limit",
        "devices_used",
        "auto_renew",
    },
    "SubscriptionEnvelope": {"subscription"},
    "DeviceOut": {
        "id",
        "name",
        "platform",
        "issued_at",
        "cert_expires_at",
        "last_seen_at",
        "is_online",
        "traffic_used_bytes",
    },
    "CreateDeviceIn": {"name", "platform"},
    "IssuedDeviceOut": {"device", "p12_password", "download_url", "download_expires_at"},
    "ConnectionOut": {"server_host", "gateway_url"},
}


def test_every_model_has_exactly_the_fields_of_the_frontend_contract() -> None:
    for name, fields in FIELDS.items():
        assert set(getattr(schemas, name).model_fields) == fields, name


def test_datetimes_are_iso_8601_in_utc_with_z() -> None:
    moscow = timezone(timedelta(hours=3))
    for moment in (
        datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 30, 15, 0, tzinfo=moscow),  # тот же момент в другом поясе
    ):
        out = schemas.DeviceOut(
            id="1",
            name="x",
            platform="ios",
            issued_at=moment,
            cert_expires_at=moment,
            last_seen_at=None,
            is_online=False,
            traffic_used_bytes=0,
        )
        body = out.model_dump(mode="json")
        assert body["issued_at"] == "2026-09-30T12:00:00Z"
        assert body["last_seen_at"] is None
