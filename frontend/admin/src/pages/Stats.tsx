import { useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  useClientsStats,
  useEconomics,
  useRevenueStats,
  useTrafficStats,
} from "../api/hooks/stats";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { formatBytes, formatMoney } from "../lib/format";
import { useUrlFilters } from "../lib/useUrlFilters";
import { useReferralStats } from "../api/hooks/referrals";
import { Card } from "../ui/Card";
import { CountChart, RevenueChart, TrafficChart } from "../ui/charts";
import { DataTable, type Column } from "../ui/DataTable";
import { ExportButton } from "../ui/ExportButton";
import { Field, inputClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { SmallBox } from "../ui/SmallBox";

const PERIODS = [7, 30, 90, 365] as const;
const DEFAULT_PERIOD = 30;
const KEYS = ["days"] as const;

function parsePeriod(raw: string | undefined): number {
  const n = Number(raw);
  return (PERIODS as readonly number[]).includes(n) ? n : DEFAULT_PERIOD;
}

export function StatsPage() {
  const { t } = useT();
  const navigate = useNavigate();
  const { values, set } = useUrlFilters(KEYS);
  const days = parsePeriod(values.days);

  const traffic = useTrafficStats(days);
  const revenue = useRevenueStats(days);
  const clients = useClientsStats(days);
  const economics = useEconomics();
  const referrals = useReferralStats();
  const [pickedCurrency, setPickedCurrency] = useState<string | null>(null);

  const currencies = revenue.data?.totals.map((x) => x.currency) ?? [];
  const currency =
    pickedCurrency && currencies.includes(pickedCurrency) ? pickedCurrency : (currencies[0] ?? "");
  const failed = <Notice tone="danger" text={t("common.error")} />;
  const noData = t("stats.noData");

  const topColumns: Column<S<"TopClient">>[] = [
    { key: "name", header: t("clients.name"), render: (c) => c.name },
    { key: "user", header: "@", render: (c) => (c.username ? `@${c.username}` : "—") },
    { key: "in", header: "↓", render: (c) => formatBytes(c.bytes_in) },
    { key: "out", header: "↑", render: (c) => formatBytes(c.bytes_out) },
    { key: "sum", header: t("stats.total"), render: (c) => formatBytes(c.bytes_in + c.bytes_out) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-normal">{t("nav.stats")}</h1>
        <div className="flex items-end gap-3">
        <ExportButton kind="traffic" params={{ days }} />
        <Field label={t("stats.period")}>
          <select
            className={inputClass}
            value={days}
            onChange={(e) => set({ days: e.target.value === String(DEFAULT_PERIOD) ? undefined : e.target.value })}
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {t("stats.periodDays", { n: p })}
              </option>
            ))}
          </select>
        </Field>
        </div>
      </div>

      <section aria-label={t("stats.kpis")} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {economics.error && failed}
          {economics.data &&
            Object.entries(economics.data.mrr).map(([cur, minor]) => (
              <SmallBox key={`mrr-${cur}`} color="ok" icon="dollar" value={formatMoney(minor, cur)} label={t("stats.mrr")} />
            ))}
          {economics.data &&
            Object.entries(economics.data.arpu).map(([cur, minor]) => (
              <SmallBox key={`arpu-${cur}`} color="info" icon="users" value={formatMoney(minor, cur)} label={t("stats.arpu")} />
            ))}
          {economics.data && (
            <SmallBox color="accent" icon="refresh" value={economics.data.active_paid} label={t("stats.activePaid")} />
          )}
          {clients.error && failed}
          {clients.data && (
            <>
              <SmallBox color="info" icon="users" value={clients.data.total} label={t("stats.totalClients")} />
              <SmallBox color="warn" icon="user" value={clients.data.new_in_period} label={t("stats.newClients")} />
              <SmallBox color="ok" icon="card" value={clients.data.paying_in_period} label={t("stats.payingClients")} />
            </>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title={t("stats.trafficByDay")}>
          {traffic.error ? failed : traffic.data && (
            <TrafficChart data={traffic.data.days} inLabel={t("stats.rx")} outLabel={t("stats.tx")} />
          )}
        </Card>
        <Card
          title={t("stats.revenueByDay")}
          action={
            currencies.length > 1 && (
              <select
                aria-label={t("plans.currency")}
                className={inputClass}
                value={currency}
                onChange={(e) => setPickedCurrency(e.target.value)}
              >
                {currencies.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            )
          }
        >
          {revenue.error ? failed : revenue.data && currency === "" ? (
            <p className="text-muted">{noData}</p>
          ) : (
            revenue.data && <RevenueChart data={revenue.data.series} currency={currency} label={t("stats.revenue")} />
          )}
        </Card>
        <Card title={t("stats.newClientsByDay")}>
          {clients.error ? failed : clients.data && (
            <CountChart data={clients.data.series} label={t("stats.newClients")} />
          )}
        </Card>
        <Card title={t("stats.revenuePeriod")}>
          {revenue.error ? failed : revenue.data && revenue.data.totals.length === 0 ? (
            <p className="text-muted">{noData}</p>
          ) : (
            <ul className="space-y-2">
              {revenue.data?.totals.map((x) => (
                <li key={x.currency}>
                  <div className="text-2xl font-bold">{formatMoney(x.amount, x.currency)}</div>
                  <div className="text-muted">
                    {t("stats.payments", { n: x.count })}
                    {x.refunded_count > 0 &&
                      ` · ${t("stats.refunds")}: ${formatMoney(x.refunded_amount, x.currency)} (${x.refunded_count})`}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {referrals.data && (
        <Card title={t("nav.referrals")}>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
            <div>
              <dt className="text-muted">{t("referrals.invited")}</dt>
              <dd className="text-xl font-semibold">{referrals.data.invited}</dd>
            </div>
            <div>
              <dt className="text-muted">{t("referrals.paying")}</dt>
              <dd className="text-xl font-semibold">{referrals.data.paying}</dd>
            </div>
            <div>
              <dt className="text-muted">{t("referrals.conversion")}</dt>
              <dd className="text-xl font-semibold">{referrals.data.conversion_percent}%</dd>
            </div>
            <div>
              <dt className="text-muted">{t("referrals.daysGiven")}</dt>
              <dd className="text-xl font-semibold">{referrals.data.days_given}</dd>
            </div>
          </dl>
          <Link to="/referrals" className="mt-2 inline-block text-accent">
            {t("stats.more")} →
          </Link>
        </Card>
      )}

      <Card title={t("stats.topClients")}>
        {traffic.error ? (
          failed
        ) : (
          <DataTable
            columns={topColumns}
            rows={traffic.data?.top_clients}
            rowKey={(c) => c.client_id}
            loading={traffic.isPending}
            emptyText={noData}
            onRowClick={(c) => void navigate(`/clients/${c.client_id}`)}
          />
        )}
      </Card>
    </div>
  );
}
