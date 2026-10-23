import { useState } from "react";
import { useReprocessWebhook, useWebhook, useWebhooks } from "../api/hooks/payments";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatDateTime } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { DataTable, type Column } from "../ui/DataTable";
import { buttonClass, Field, inputClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { Pagination } from "../ui/Pagination";
import { StatusBadge, type Tone } from "../ui/StatusBadge";

const KEYS = ["status", "provider"] as const;
const STATUSES = ["received", "processed", "ignored", "failed", "dead", "rejected"];
const TONE: Record<string, Tone> = { processed: "ok", failed: "danger", dead: "danger", rejected: "warn" };

function Detail({ id }: { id: number }) {
  const { data } = useWebhook(id);
  if (!data) return null;
  return (
    <pre className="mt-2 max-h-72 overflow-auto rounded-md border border-border p-2 text-xs">
      {JSON.stringify(data.payload, null, 2)}
    </pre>
  );
}

export function WebhooksTab() {
  const { t } = useT();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);
  const query = useWebhooks({ status: values.status, provider: values.provider, limit, offset });
  const reprocess = useReprocessWebhook();
  const [open, setOpen] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const columns: Column<S<"WebhookOut">>[] = [
    { key: "at", header: t("payments.received"), render: (w) => formatDateTime(w.received_at) },
    { key: "provider", header: t("payments.provider"), render: (w) => w.provider },
    {
      key: "event",
      header: t("webhooks.event"),
      render: (w) => (
        <div>
          <div>{w.external_event_id}</div>
          {w.last_error && <div className="text-xs text-danger">{w.last_error}</div>}
          {open === w.id && <Detail id={w.id} />}
        </div>
      ),
    },
    {
      key: "status",
      header: t("clients.status"),
      render: (w) => <StatusBadge tone={TONE[w.status] ?? "neutral"} label={w.status} />,
    },
    { key: "attempts", header: t("webhooks.attempts"), render: (w) => w.attempts },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (w) => (
        <span className="flex justify-end gap-2">
          <button className={buttonClass} onClick={() => setOpen(open === w.id ? null : w.id)}>
            {t("webhooks.details")}
          </button>
          {(w.status === "failed" || w.status === "dead") && (
            <button
              className={buttonClass}
              disabled={reprocess.isPending}
              onClick={() => reprocess.mutate(w.id, { onSuccess: () => setNotice(t("action.done")) })}
            >
              {t("webhooks.reprocess")}
            </button>
          )}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("clients.status")}>
          <select className={inputClass} value={values.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">{t("webhooks.needAttention")}</option>
            <option value="all">{t("common.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("payments.provider")}>
          <input className={inputClass} value={values.provider ?? ""} onChange={(e) => set({ provider: e.target.value || undefined })} />
        </Field>
      </div>
      <Notice text={notice} />
      {reprocess.error && <Notice tone="danger" text={errorText(reprocess.error, t("common.error"))} />}
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(w) => w.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
      />
      {query.data && <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />}
    </div>
  );
}
