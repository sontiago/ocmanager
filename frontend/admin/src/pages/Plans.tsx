import { useState } from "react";
import { usePlans } from "../api/hooks/plans";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { formatBytes, formatMoney } from "../lib/format";
import { DataTable, type Column } from "../ui/DataTable";
import { buttonClass, primaryButtonClass } from "../ui/Field";
import { StatusBadge } from "../ui/StatusBadge";
import { PlanFormDialog } from "./PlanForm";

type Editing = S<"PlanOut"> | "new" | null;

export function PlansPage() {
  const { t, lang } = useT();
  const query = usePlans();
  const [editing, setEditing] = useState<Editing>(null);

  const columns: Column<S<"PlanOut">>[] = [
    {
      key: "name",
      header: t("plans.name"),
      render: (p) => (
        <span>
          {p.name_i18n[lang] ?? p.code} <span className="text-muted">{p.code}</span>{" "}
          {p.is_trial && <StatusBadge label="trial" />}
          {!p.is_active && <StatusBadge tone="warn" label={t("plans.inactive")} />}
        </span>
      ),
    },
    { key: "price", header: t("plans.price"), render: (p) => formatMoney(p.price_amount, p.currency) },
    { key: "days", header: t("plans.duration"), render: (p) => p.duration_days },
    { key: "devices", header: t("plans.deviceLimit"), render: (p) => p.device_limit },
    {
      key: "traffic",
      header: t("client.traffic"),
      render: (p) => (p.traffic_limit_bytes === null ? "∞" : formatBytes(p.traffic_limit_bytes)),
    },
    {
      key: "edit",
      header: "",
      className: "text-right",
      render: (p) => (
        <button
          className={buttonClass}
          aria-label={t("plans.editNamed", { name: p.name_i18n[lang] ?? p.code })}
          onClick={() => setEditing(p)}
        >
          {t("common.edit")}
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{t("nav.plans")}</h1>
        <button className={primaryButtonClass} onClick={() => setEditing("new")}>
          {t("plans.new")}
        </button>
      </div>
      <DataTable
        columns={columns}
        rows={query.data}
        rowKey={(p) => p.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
      />
      {editing !== null && (
        <PlanFormDialog plan={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
