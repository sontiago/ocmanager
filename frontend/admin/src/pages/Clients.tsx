import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useClients } from "../api/hooks/clients";
import { useT } from "../i18n";
import { formatDateTime } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { useUrlFilters } from "../lib/useUrlFilters";
import { DataTable, type Column } from "../ui/DataTable";
import { Field, inputClass } from "../ui/Field";
import { Pagination } from "../ui/Pagination";
import { StatusBadge } from "../ui/StatusBadge";
import type { S } from "../api/types";

const KEYS = ["q", "status", "blocked"] as const;
export const CLIENT_STATUSES = [
  "pending_payment",
  "trial",
  "active",
  "expired",
  "exhausted",
  "cancelled",
  "blocked",
  "none",
] as const;

export function ClientsPage() {
  const { t } = useT();
  const navigate = useNavigate();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);

  const [text, setText] = useState(values.q ?? "");
  const debounced = useDebounced(text, 300);
  useEffect(() => {
    if (debounced !== (values.q ?? "")) set({ q: debounced });
    // values.q намеренно вне зависимостей: иначе правка URL извне перезаписывалась бы старым текстом
  }, [debounced]);

  const query = useClients({
    q: values.q,
    status: values.status,
    blocked: values.blocked === undefined ? undefined : values.blocked === "true",
    limit,
    offset,
  });

  const columns: Column<S<"ClientRow">>[] = [
    {
      key: "name",
      header: t("clients.name"),
      render: (c) => (
        <span>
          {c.first_name} {c.username && <span className="text-muted">@{c.username}</span>}
        </span>
      ),
    },
    { key: "tg", header: "Telegram ID", render: (c) => c.telegram_id },
    {
      key: "sub",
      header: t("clients.subscription"),
      render: (c) =>
        c.subscription_status ? (
          <span>
            {t(`sub.status.${c.subscription_status}`)} · {c.plan_code}
          </span>
        ) : (
          <span className="text-muted">{t("sub.status.none")}</span>
        ),
    },
    { key: "exp", header: t("clients.expires"), render: (c) => formatDateTime(c.expires_at) },
    { key: "dev", header: t("clients.devices"), render: (c) => c.devices_active },
    {
      key: "blocked",
      header: "",
      render: (c) => (c.is_blocked ? <StatusBadge tone="danger" label={t("clients.blocked")} /> : null),
    },
  ];

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t("nav.clients")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-80">
          <Field label={t("clients.search")}>
            <input
              className={inputClass}
              placeholder={t("clients.searchPlaceholder")}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </Field>
        </div>
        <Field label={t("clients.status")}>
          <select
            className={inputClass}
            value={values.status ?? ""}
            onChange={(e) => set({ status: e.target.value || undefined })}
          >
            <option value="">{t("common.all")}</option>
            {CLIENT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`sub.status.${s}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("clients.blockedFilter")}>
          <select
            className={inputClass}
            value={values.blocked ?? ""}
            onChange={(e) => set({ blocked: e.target.value || undefined })}
          >
            <option value="">{t("common.all")}</option>
            <option value="true">{t("common.yes")}</option>
            <option value="false">{t("common.no")}</option>
          </select>
        </Field>
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(c) => c.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
        onRowClick={(c) => void navigate(`/clients/${c.id}`)}
      />
      {query.data && (
        <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
      )}
    </div>
  );
}
