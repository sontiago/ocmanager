import { useState } from "react";
import { useAudit } from "../api/hooks/audit";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { dayStartUtc } from "../lib/dates";
import { formatDateTime } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { DataTable, type Column } from "../ui/DataTable";
import { ExportButton } from "../ui/ExportButton";
import { buttonClass, Field, inputClass } from "../ui/Field";
import { Pagination } from "../ui/Pagination";

const KEYS = ["actor_type", "action", "target_type", "target_id", "since", "until"] as const;

export function AuditPage() {
  const { t } = useT();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);
  const [open, setOpen] = useState<number | null>(null);
  const filters = {
    actor_type: values.actor_type,
    action: values.action,
    target_type: values.target_type,
    target_id: values.target_id,
    since: dayStartUtc(values.since),
    until: dayStartUtc(values.until, 1),
  };
  const query = useAudit({ ...filters, limit, offset });

  const text = (key: (typeof KEYS)[number], label: string) => (
    <Field label={label}>
      <input
        className={inputClass}
        value={values[key] ?? ""}
        onChange={(e) => set({ [key]: e.target.value || undefined })}
      />
    </Field>
  );

  const columns: Column<S<"AuditRow">>[] = [
    { key: "at", header: t("audit.time"), render: (a) => formatDateTime(a.created_at) },
    {
      key: "actor",
      header: t("audit.actor"),
      render: (a) => `${a.actor_type}${a.actor_id ? ` #${a.actor_id}` : ""}`,
    },
    {
      key: "action",
      header: t("audit.action"),
      render: (a) => (
        <div>
          <div>{a.action}</div>
          {open === a.id && (
            <pre className="mt-1 max-h-60 overflow-auto rounded-md border border-border p-2 text-xs">
              {JSON.stringify(a.details, null, 2)}
            </pre>
          )}
        </div>
      ),
    },
    {
      key: "target",
      header: t("audit.target"),
      render: (a) => (a.target_type ? `${a.target_type} ${a.target_id ?? ""}` : "—"),
    },
    { key: "ip", header: "IP", render: (a) => a.ip ?? "—" },
    {
      key: "details",
      header: "",
      render: (a) => (
        <button className={buttonClass} onClick={() => setOpen(open === a.id ? null : a.id)}>
          {t("audit.details")}
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-normal">{t("nav.audit")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("audit.actor")}>
          <select
            className={inputClass}
            value={values.actor_type ?? ""}
            onChange={(e) => set({ actor_type: e.target.value || undefined })}
          >
            <option value="">{t("common.all")}</option>
            <option value="admin">admin</option>
            <option value="system">system</option>
            <option value="client">client</option>
          </select>
        </Field>
        {text("action", t("audit.action"))}
        {text("target_type", t("audit.targetType"))}
        {text("target_id", t("audit.targetId"))}
        <Field label={t("payments.since")}>
          <input className={inputClass} type="date" value={values.since ?? ""} onChange={(e) => set({ since: e.target.value || undefined })} />
        </Field>
        <Field label={t("payments.until")}>
          <input className={inputClass} type="date" value={values.until ?? ""} onChange={(e) => set({ until: e.target.value || undefined })} />
        </Field>
        <ExportButton kind="audit" params={filters} />
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(a) => a.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
      />
      {query.data && <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />}
    </div>
  );
}
