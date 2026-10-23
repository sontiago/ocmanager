import { useState } from "react";
import { Link } from "react-router";
import { usePlans } from "../api/hooks/plans";
import { useCancelAutoRenew, useExpire, useSubscriptions } from "../api/hooks/subscriptions";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatBytes, formatDateTime } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { DataTable, type Column } from "../ui/DataTable";
import { ExportButton } from "../ui/ExportButton";
import { buttonClass, Field, inputClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { Pagination } from "../ui/Pagination";
import { StatusBadge } from "../ui/StatusBadge";

const KEYS = ["status", "plan", "expiring_within_days"] as const;
const STATUSES = ["pending_payment", "trial", "active", "expired", "exhausted", "cancelled", "blocked"];

export function SubscriptionsPage() {
  const { t } = useT();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);
  const plans = usePlans();
  const cancel = useCancelAutoRenew();
  const expire = useExpire();
  const [toExpire, setToExpire] = useState<S<"SubscriptionRow"> | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const days = values.expiring_within_days;
  const query = useSubscriptions({
    status: values.status,
    plan: values.plan,
    expiring_within_days: days === undefined || Number.isNaN(Number(days)) ? undefined : Number(days),
    limit,
    offset,
  });

  const columns: Column<S<"SubscriptionRow">>[] = [
    {
      key: "client",
      header: t("clients.name"),
      render: (r) => (
        <Link to={`/clients/${r.client_id}`} className="text-accent">
          {r.first_name} {r.username && `@${r.username}`}
        </Link>
      ),
    },
    { key: "status", header: t("clients.status"), render: (r) => t(`sub.status.${r.status}`) },
    {
      key: "plan",
      header: t("nav.plans"),
      render: (r) => (
        <span>
          {r.plan_code} {r.plan_is_trial && <StatusBadge label="trial" />}
        </span>
      ),
    },
    { key: "exp", header: t("clients.expires"), render: (r) => formatDateTime(r.expires_at) },
    {
      key: "traffic",
      header: t("client.traffic"),
      render: (r) =>
        `${formatBytes(r.traffic_used_bytes)}${r.traffic_limit_bytes === null ? "" : ` / ${formatBytes(r.traffic_limit_bytes)}`}`,
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (r) => (
        <span className="flex justify-end gap-2">
          {r.auto_renew && (
            <button
              className={buttonClass}
              onClick={() =>
                cancel.mutate(r.client_id, {
                  onSuccess: (a) => setNotice(a.changed ? t("action.done") : t("action.noChange")),
                })
              }
            >
              {t("subs.cancelAutoRenew")}
            </button>
          )}
          <button className={buttonClass} onClick={() => setToExpire(r)}>
            {t("subs.expire")}
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-normal">{t("nav.subscriptions")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("clients.status")}>
          <select
            className={inputClass}
            value={values.status ?? ""}
            onChange={(e) => set({ status: e.target.value || undefined })}
          >
            <option value="">{t("common.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`sub.status.${s}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("nav.plans")}>
          <select
            className={inputClass}
            value={values.plan ?? ""}
            onChange={(e) => set({ plan: e.target.value || undefined })}
          >
            <option value="">{t("common.all")}</option>
            {plans.data?.map((p) => (
              <option key={p.code} value={p.code}>
                {p.code}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("subs.expiringWithin")}>
          <input
            className={inputClass}
            type="number"
            min={0}
            value={values.expiring_within_days ?? ""}
            onChange={(e) => set({ expiring_within_days: e.target.value || undefined })}
          />
        </Field>
        <ExportButton
          kind="subscriptions"
          params={{
            status: values.status,
            plan: values.plan,
            expiring_within_days: values.expiring_within_days,
          }}
        />
      </div>
      <Notice text={notice} />
      {(cancel.error || expire.error) && (
        <Notice tone="danger" text={errorText(cancel.error ?? expire.error, t("common.error"))} />
      )}
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(r) => r.client_id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
      />
      {query.data && (
        <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
      )}
      <ConfirmDialog
        open={toExpire !== null}
        title={t("subs.expireTitle")}
        body={t("subs.expireBody")}
        confirmLabel={t("subs.expire")}
        danger
        pending={expire.isPending}
        onCancel={() => setToExpire(null)}
        onConfirm={() =>
          toExpire &&
          expire.mutate(toExpire.client_id, {
            onSuccess: (a) => {
              setToExpire(null);
              setNotice(a.changed ? t("action.done") : t("action.noChange"));
            },
          })
        }
      />
    </div>
  );
}
