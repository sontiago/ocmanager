import { Link } from "react-router";
import { usePayments } from "../api/hooks/payments";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { formatDateTime, formatMoney } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { DataTable, type Column } from "../ui/DataTable";
import { Field, inputClass } from "../ui/Field";
import { Pagination } from "../ui/Pagination";
import { StatusBadge } from "../ui/StatusBadge";

const KEYS = ["client_id", "status", "since", "until"] as const;

/** Начало суток UTC для даты `YYYY-MM-DD`, сдвинутое на `plusDays`. */
function dayStartUtc(day: string | undefined, plusDays = 0): string | undefined {
  if (!day) return undefined;
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return undefined;
  d.setUTCDate(d.getUTCDate() + plusDays);
  return d.toISOString();
}

export function PaymentsTab() {
  const { t } = useT();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);
  const clientId = Number(values.client_id);
  const query = usePayments({
    client_id: Number.isInteger(clientId) && clientId > 0 ? clientId : undefined,
    status: values.status,
    since: dayStartUtc(values.since),
    // «По дату» включительно, а бэкенд сравнивает `< until`: уходит начало следующих суток.
    until: dayStartUtc(values.until, 1),
    limit,
    offset,
  });

  const columns: Column<S<"PaymentOut">>[] = [
    { key: "at", header: t("payments.received"), render: (p) => formatDateTime(p.received_at) },
    {
      key: "client",
      header: t("clients.name"),
      render: (p) => (
        <Link to={`/clients/${p.client_id}`} className="text-accent">
          #{p.client_id}
        </Link>
      ),
    },
    { key: "amount", header: t("payments.amount"), render: (p) => formatMoney(p.amount, p.currency) },
    { key: "provider", header: t("payments.provider"), render: (p) => p.provider },
    { key: "status", header: t("clients.status"), render: (p) => p.status },
    {
      key: "processed",
      header: "",
      render: (p) =>
        p.processed_at === null ? <StatusBadge tone="warn" label={t("overview.unprocessed")} /> : null,
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("payments.since")}>
          <input className={inputClass} type="date" value={values.since ?? ""} onChange={(e) => set({ since: e.target.value || undefined })} />
        </Field>
        <Field label={t("payments.until")}>
          <input className={inputClass} type="date" value={values.until ?? ""} onChange={(e) => set({ until: e.target.value || undefined })} />
        </Field>
        <Field label={t("clients.status")}>
          <select className={inputClass} value={values.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">{t("common.all")}</option>
            <option value="succeeded">succeeded</option>
            <option value="refunded">refunded</option>
          </select>
        </Field>
        <Field label={t("payments.clientId")}>
          <input className={inputClass} inputMode="numeric" value={values.client_id ?? ""} onChange={(e) => set({ client_id: e.target.value || undefined })} />
        </Field>
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(p) => p.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
        emptyText={t("overview.noPayments")}
      />
      {query.data && <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />}
    </div>
  );
}
