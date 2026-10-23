import csv
import io
from datetime import timedelta

import pytest
from conftest import MakeClient, MakePayment, MakeSubscription
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.routers import export
from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow

KINDS = ["clients", "subscriptions", "payments", "audit", "traffic"]


def parse(r: Response) -> list[dict[str, str]]:
    assert r.status_code == 200, r.text
    text = r.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


@pytest.mark.parametrize("kind", KINDS)
async def test_a_session_is_required(anon_client: AsyncClient, kind: str) -> None:
    assert (await anon_client.get(f"/admin/export/{kind}.csv")).status_code == 401


async def test_an_unknown_kind_is_404(admin_client: AsyncClient) -> None:
    assert (await admin_client.get("/admin/export/secrets.csv")).status_code == 404


async def test_the_response_is_an_excel_friendly_csv_download(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    await make_client(first_name="Анна")
    r = await admin_client.get("/admin/export/clients.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")  # BOM: Excel иначе читает кириллицу как cp1251
    today = utcnow().date().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="ocmanager-clients-{today}.csv"'
    )
    rows = parse(r)
    assert rows[0]["first_name"] == "Анна"
    assert list(rows[0]) == export.COLUMNS["clients"]


async def test_an_empty_export_still_has_the_header(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/admin/export/payments.csv")
    assert r.content.decode("utf-8-sig").strip() == ",".join(export.COLUMNS["payments"])


async def test_clients_are_filtered_like_the_list(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    await make_client(first_name="Alice", username="alice")
    await make_client(first_name="Bob", username="bob")
    rows = parse(await admin_client.get("/admin/export/clients.csv?q=ali"))
    assert [r["username"] for r in rows] == ["alice"]


async def test_payments_amount_is_in_major_units_and_filters_apply(
    admin_client: AsyncClient, make_client: MakeClient, make_payment: MakePayment
) -> None:
    c = await make_client()
    await make_payment(c, amount=29950, currency="RUB")
    await make_payment(c, amount=500, currency="USD", status="refunded")
    rows = parse(await admin_client.get("/admin/export/payments.csv?status=succeeded"))
    assert [(r["amount"], r["currency"], r["status"]) for r in rows] == [
        ("299.50", "RUB", "succeeded")
    ]
    assert len(parse(await admin_client.get("/admin/export/payments.csv"))) == 2


async def test_subscriptions_export_carries_the_plan(
    admin_client: AsyncClient, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    c = await make_client()
    await make_subscription(c, days=30, now=utcnow())
    rows = parse(await admin_client.get("/admin/export/subscriptions.csv?status=active"))
    assert len(rows) == 1
    assert rows[0]["client_id"] == str(c.id)
    assert rows[0]["plan_is_trial"] == "false"


async def test_audit_details_are_json_and_filters_apply(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    await admin_client.get("/admin/export/clients.csv")  # пишет export.clients
    rows = parse(await admin_client.get("/admin/export/audit.csv?action=export.clients"))
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "admin"
    assert '"rows"' in rows[0]["details"]


async def test_each_export_is_audited_with_its_filters(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    await admin_client.get("/admin/export/payments.csv?status=refunded")
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "export.payments"))
    assert row is not None
    assert row.details["filters"] == {"status": "refunded"}
    assert row.details["rows"] == 0


async def test_traffic_export_has_one_row_per_day(admin_client: AsyncClient) -> None:
    rows = parse(await admin_client.get("/admin/export/traffic.csv?days=7"))
    assert len(rows) == 7
    assert rows[-1]["day"] == utcnow().date().isoformat()
    assert rows[0]["day"] == (utcnow().date() - timedelta(days=6)).isoformat()


@pytest.mark.parametrize(
    "query", ["traffic.csv?days=0", "traffic.csv?days=367", "payments.csv?status=bogus"]
)
async def test_bad_filters_are_422(admin_client: AsyncClient, query: str) -> None:
    assert (await admin_client.get(f"/admin/export/{query}")).status_code == 422


@pytest.mark.parametrize("payload", ['=HYPERLINK("http://evil")', "+1+1", "-2+3", "@SUM(A1)"])
async def test_spreadsheet_formulas_are_defused(
    admin_client: AsyncClient, make_client: MakeClient, payload: str
) -> None:
    await make_client(first_name=payload)
    rows = parse(await admin_client.get("/admin/export/clients.csv"))
    assert rows[0]["first_name"] == "'" + payload


async def test_numbers_are_not_mangled_by_the_formula_guard(
    admin_client: AsyncClient, make_client: MakeClient, make_payment: MakePayment
) -> None:
    c = await make_client()
    await make_payment(c, amount=100)
    rows = parse(await admin_client.get("/admin/export/payments.csv"))
    assert rows[0]["amount"] == "1.00"
    assert rows[0]["client_id"] == str(c.id)


async def test_every_row_is_exported_across_pages(
    admin_client: AsyncClient, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "PAGE_SIZE", 2)
    for _ in range(5):
        await make_client()
    assert len(parse(await admin_client.get("/admin/export/clients.csv"))) == 5


async def test_the_row_cap_is_announced(
    admin_client: AsyncClient, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MAX_ROWS", 3)
    monkeypatch.setattr(export, "PAGE_SIZE", 2)
    for _ in range(5):
        await make_client()
    r = await admin_client.get("/admin/export/clients.csv")
    assert len(parse(r)) == 3
    assert r.headers["x-export-truncated"] == "true"
