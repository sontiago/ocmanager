import { Link } from "react-router";
import { useReferralStats, useRewards } from "../api/hooks/referrals";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { formatBytes, formatDateTime } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { Card } from "../ui/Card";
import { DataTable, type Column } from "../ui/DataTable";
import { Notice } from "../ui/Notice";
import { Pagination } from "../ui/Pagination";
import { SmallBox } from "../ui/SmallBox";
import { StatusBadge } from "../ui/StatusBadge";

const KEYS = ["inviter_id"] as const;

export function ReferralsPage() {
  const { t } = useT();
  const { values, limit, offset, setOffset } = useUrlFilters(KEYS);
  const id = Number(values.inviter_id);
  const stats = useReferralStats();
  const rewards = useRewards({
    inviter_id: Number.isInteger(id) && id > 0 ? id : undefined,
    limit,
    offset,
  });

  const given = (r: S<"RewardRow">) => {
    const parts: string[] = [];
    if (r.days) parts.push(t("referrals.days", { n: r.days }));
    if (r.invitee_days) parts.push(t("referrals.friendDays", { n: r.invitee_days }));
    if (r.devices) parts.push(t("referrals.devices", { n: r.devices }));
    if (r.traffic_bytes) parts.push(`+${formatBytes(r.traffic_bytes)}`);
    return parts.join(" · ") || "—";
  };

  const columns: Column<S<"RewardRow">>[] = [
    { key: "at", header: t("payments.received"), render: (r) => formatDateTime(r.created_at) },
    {
      key: "inviter",
      header: t("referrals.inviter"),
      render: (r) => (
        <Link to={`/clients/${r.inviter_id}`} className="text-accent">
          {r.inviter_name}
        </Link>
      ),
    },
    {
      key: "friend",
      header: t("referrals.friend"),
      render: (r) => (
        <Link to={`/clients/${r.invitee_id}`} className="text-accent">
          {r.invitee_name}
        </Link>
      ),
    },
    {
      key: "kind",
      header: t("referrals.kind"),
      render: (r) => (r.kind === "tier" ? t("referrals.tierN", { n: r.tier ?? 0 }) : t("referrals.base")),
    },
    { key: "given", header: t("referrals.given"), render: given },
    {
      key: "status",
      header: t("clients.status"),
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          <StatusBadge
            tone={r.status === "applied" ? "ok" : "warn"}
            label={t(`referrals.status.${r.status}`)}
          />
          {r.payment_status === "refunded" && (
            <StatusBadge tone="danger" label={t("referrals.refunded")} />
          )}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-normal">{t("nav.referrals")}</h1>

      {stats.error && <Notice tone="danger" text={t("common.error")} />}
      {stats.data && (
        <>
          <section aria-label={t("referrals.summary")}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <SmallBox color="info" icon="users" value={stats.data.invited} label={t("referrals.invited")} />
              <SmallBox color="ok" icon="card" value={stats.data.paying} label={t("referrals.paying")} />
              <SmallBox color="warn" icon="activity" value={`${stats.data.conversion_percent}%`} label={t("referrals.conversion")} />
              <SmallBox color="accent" icon="clock" value={stats.data.days_given} label={t("referrals.daysGiven")} />
              <SmallBox color="info" icon="phone" value={stats.data.devices_given} label={t("referrals.devicesGiven")} />
              <SmallBox color="ok" icon="server" value={formatBytes(stats.data.traffic_bytes_given)} label={t("referrals.trafficGiven")} />
            </div>
          </section>
          <Card title={t("referrals.tiers")}>
            <ul className="space-y-1">
              {stats.data.tiers.map((x) => (
                <li key={x.friends} className="flex justify-between">
                  <span>{t("referrals.tierN", { n: x.friends })}</span>
                  <span className="font-medium">{x.reached}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}

      <Card title={t("referrals.log")}>
        <DataTable
          columns={columns}
          rows={rewards.data?.items}
          rowKey={(r) => r.id}
          loading={rewards.isPending}
          error={rewards.error ? t("common.error") : null}
          emptyText={t("referrals.empty")}
        />
        {rewards.data && (
          <Pagination total={rewards.data.total} limit={limit} offset={offset} onChange={setOffset} />
        )}
      </Card>
    </div>
  );
}
