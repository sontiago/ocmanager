import type { ReactNode } from "react";
import { Link } from "react-router";
import { useOverview } from "../api/hooks/overview";
import { useT } from "../i18n";
import { formatBytes, formatDateTime, formatMoney, relativeTime } from "../lib/format";
import { Card } from "../ui/Card";
import { StatusBadge, type Tone } from "../ui/StatusBadge";

const STATE_TONE: Record<string, Tone> = { online: "ok", degraded: "warn", offline: "danger" };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-muted">{label}</span>
      <span className="font-medium">{children}</span>
    </div>
  );
}

export function OverviewPage() {
  const { t } = useT();
  const { data, error, isPending } = useOverview();

  if (error) {
    return (
      <p role="alert" className="rounded-md border border-danger p-3 text-danger">
        {t("common.error")}
      </p>
    );
  }
  if (isPending) return <p className="text-muted">{t("common.loading")}</p>;

  const noData = <span className="text-muted">{t("common.noData")}</span>;
  const health = data.health;
  const revenue = Object.entries(data.revenue);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{t("overview.title")}</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t("overview.service")}>
          <div className="space-y-3">
            {data.node === null ? (
              <p className="text-muted">{t("overview.noNode")}</p>
            ) : (
              <div>
                <Row label={t("overview.node")}>
                  {data.node.name}{" "}
                  {health ? (
                    <StatusBadge
                      tone={STATE_TONE[health.state] ?? "neutral"}
                      label={t(`node.state.${health.state}`)}
                    />
                  ) : (
                    noData
                  )}
                </Row>
                <Row label={t("overview.reconcile")}>
                  {data.node.last_reconcile_at ? relativeTime(data.node.last_reconcile_at) : noData}
                </Row>
              </div>
            )}
            <Row label={t("overview.sessions")}>
              {data.active_sessions === null ? noData : data.active_sessions}
            </Row>
            <Row label={t("overview.traffic")}>
              ↓ {formatBytes(data.traffic.bytes_in)} · ↑ {formatBytes(data.traffic.bytes_out)}
            </Row>
            {data.webhooks_needing_attention > 0 && (
              <Link to="/payments?tab=webhooks" className="block rounded-md border border-warn p-2 text-warn">
                {t("overview.webhooks", { n: data.webhooks_needing_attention })}
              </Link>
            )}
            <div>
              <h3 className="mb-1 text-xs text-muted uppercase">{t("overview.audit")}</h3>
              {data.recent_audit.length === 0 && (
                <p className="text-muted">{t("overview.noAudit")}</p>
              )}
              <ul className="space-y-1">
                {data.recent_audit.map((a) => (
                  <li key={a.id} className="flex justify-between gap-2">
                    <span>
                      <span className="text-muted">{a.actor_type}</span> {a.action}
                    </span>
                    <span className="text-muted">{relativeTime(a.created_at)}</span>
                  </li>
                ))}
              </ul>
              <Link to="/audit" className="mt-1 inline-block text-accent">
                {t("nav.audit")} →
              </Link>
            </div>
          </div>
        </Card>

        <Card title={t("overview.money")}>
          <div className="space-y-3">
            <div>
              <h3 className="mb-1 text-xs text-muted uppercase">{t("overview.revenue")}</h3>
              {revenue.length === 0 && <p className="text-muted">{t("overview.noRevenue")}</p>}
              {revenue.map(([currency, minor]) => (
                <p key={currency} className="text-2xl font-semibold">
                  {formatMoney(minor, currency)}
                </p>
              ))}
            </div>
            <div>
              <h3 className="mb-1 text-xs text-muted uppercase">{t("overview.subscriptions")}</h3>
              {Object.entries(data.subscriptions_by_status).map(([status, count]) => (
                <Link
                  key={status}
                  to={`/subscriptions?status=${status}`}
                  className="flex justify-between py-0.5 hover:text-accent"
                >
                  <span>{status}</span>
                  <span className="font-medium">{count}</span>
                </Link>
              ))}
              <Link
                to="/subscriptions?expiring_within_days=3"
                className="mt-1 flex justify-between py-0.5 hover:text-accent"
              >
                <span>{t("overview.expiring")}</span>
                <span className="font-medium">{data.expiring_soon}</span>
              </Link>
            </div>
            <div>
              <h3 className="mb-1 text-xs text-muted uppercase">{t("overview.payments")}</h3>
              {data.recent_payments.length === 0 && (
                <p className="text-muted">{t("overview.noPayments")}</p>
              )}
              <ul className="space-y-1">
                {data.recent_payments.map((p) => (
                  <li key={p.id} className="flex justify-between gap-2">
                    <span>
                      {formatMoney(p.amount, p.currency)}{" "}
                      {p.processed_at === null && (
                        <StatusBadge tone="warn" label={t("overview.unprocessed")} />
                      )}
                    </span>
                    <span className="text-muted">{formatDateTime(p.received_at)}</span>
                  </li>
                ))}
              </ul>
              <Link to="/payments" className="mt-1 inline-block text-accent">
                {t("nav.payments")} →
              </Link>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
