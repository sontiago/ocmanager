import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import {
  useBlockClient,
  useClient,
  useExtend,
  useGrant,
  useUnblockClient,
} from "../api/hooks/clients";
import { usePlans } from "../api/hooks/plans";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatBytes, formatDateTime, formatMoney } from "../lib/format";
import { Card } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { DataTable } from "../ui/DataTable";
import { buttonClass, dangerButtonClass, Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Modal } from "../ui/Modal";
import { Notice } from "../ui/Notice";
import { StatusBadge } from "../ui/StatusBadge";
import { IssueDeviceDialog } from "./IssueDeviceDialog";

type Dialog = "block" | "grant" | "extend" | "issue" | null;

function GrantForm({ clientId, onDone }: { clientId: number; onDone(changed: boolean): void }) {
  const { t, lang } = useT();
  const plans = usePlans();
  const grant = useGrant(clientId);
  const [plan, setPlan] = useState("");
  const [days, setDays] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    grant.mutate(
      { plan_code: plan, ...(days ? { days: Number(days) } : {}) },
      { onSuccess: (r) => onDone(r.changed) },
    );
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label={t("grant.plan")}>
        <select className={inputClass} value={plan} onChange={(e) => setPlan(e.target.value)} required>
          <option value="" />
          {plans.data?.map((p) => (
            <option key={p.code} value={p.code}>
              {p.name_i18n[lang] ?? p.code}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("grant.days")}>
        <input className={inputClass} type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} />
      </Field>
      {grant.error && <Notice tone="danger" text={errorText(grant.error, t("common.error"))} />}
      <div className="flex justify-end">
        <button type="submit" className={primaryButtonClass} disabled={grant.isPending || !plan}>
          {t("grant.submit")}
        </button>
      </div>
    </form>
  );
}

function ExtendForm({ clientId, onDone }: { clientId: number; onDone(changed: boolean): void }) {
  const { t } = useT();
  const extend = useExtend(clientId);
  const [days, setDays] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    extend.mutate({ days: Number(days) }, { onSuccess: (r) => onDone(r.changed) });
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label={t("extend.days")}>
        <input className={inputClass} type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} required />
      </Field>
      {extend.error && <Notice tone="danger" text={errorText(extend.error, t("common.error"))} />}
      <div className="flex justify-end">
        <button type="submit" className={primaryButtonClass} disabled={extend.isPending || !days}>
          {t("extend.submit")}
        </button>
      </div>
    </form>
  );
}

export function ClientDetailPage() {
  const { t, lang } = useT();
  const id = Number(useParams().id);
  const query = useClient(id);
  const block = useBlockClient(id);
  const unblock = useUnblockClient(id);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (query.error) return <Notice tone="danger" text={t("common.error")} />;
  if (!query.data) return <p className="text-muted">{t("common.loading")}</p>;

  const { client, subscription: sub, devices, payments, sessions } = query.data;
  const done = (changed: boolean) => {
    setDialog(null);
    setNotice(changed ? t("action.done") : t("action.noChange"));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-normal">
          {client.first_name} {client.username && <span className="text-muted">@{client.username}</span>}{" "}
          {client.is_blocked && <StatusBadge tone="danger" label={t("clients.blocked")} />}
        </h1>
        <div className="flex flex-wrap gap-2">
          <button className={buttonClass} onClick={() => setDialog("grant")}>
            {t("client.grant")}
          </button>
          <button className={buttonClass} onClick={() => setDialog("extend")} disabled={!sub}>
            {t("client.extend")}
          </button>
          <button className={buttonClass} onClick={() => setDialog("issue")}>
            {t("device.issue")}
          </button>
          {client.is_blocked ? (
            <button
              className={buttonClass}
              disabled={unblock.isPending}
              onClick={() =>
                unblock.mutate(undefined, { onSuccess: (r) => done(r.changed) })
              }
            >
              {t("client.unblock")}
            </button>
          ) : (
            <button className={dangerButtonClass} onClick={() => setDialog("block")}>
              {t("client.block")}
            </button>
          )}
        </div>
      </div>
      <Notice text={notice} />
      {(unblock.error || block.error) && (
        <Notice tone="danger" text={errorText(unblock.error ?? block.error, t("common.error"))} />
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t("client.profile")}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">Telegram ID</dt>
            <dd>{client.telegram_id}</dd>
            <dt className="text-muted">{t("client.lang")}</dt>
            <dd>{client.lang}</dd>
            <dt className="text-muted">{t("client.created")}</dt>
            <dd>{formatDateTime(client.created_at)}</dd>
            <dt className="text-muted">{t("client.trialUsed")}</dt>
            <dd>{formatDateTime(client.trial_used_at)}</dd>
          </dl>
        </Card>
        <Card title={t("clients.subscription")}>
          {!sub ? (
            <p className="text-muted">{t("sub.status.none")}</p>
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted">{t("clients.status")}</dt>
              <dd>{t(`sub.status.${sub.status}`)}</dd>
              <dt className="text-muted">{t("nav.plans")}</dt>
              <dd>{sub.plan_name_i18n[lang] ?? sub.plan_code}</dd>
              <dt className="text-muted">{t("clients.expires")}</dt>
              <dd>{formatDateTime(sub.expires_at)}</dd>
              <dt className="text-muted">{t("clients.devices")}</dt>
              <dd>
                {sub.devices_active} / {sub.device_limit}{" "}
                {sub.over_device_limit && <StatusBadge tone="warn" label={t("client.overLimit")} />}
              </dd>
              <dt className="text-muted">{t("client.traffic")}</dt>
              <dd>
                {formatBytes(sub.traffic_used_bytes)}
                {sub.traffic_limit_bytes !== null && ` / ${formatBytes(sub.traffic_limit_bytes)}`}
              </dd>
            </dl>
          )}
        </Card>
      </div>

      <Card title={t("nav.devices")}>
        <DataTable
          rows={devices}
          rowKey={(d) => d.id}
          columns={[
            { key: "name", header: t("device.name"), render: (d) => d.name },
            { key: "platform", header: t("device.platform"), render: (d) => d.platform },
            { key: "user", header: "username", render: (d) => d.username },
            { key: "seen", header: t("device.lastSeen"), render: (d) => formatDateTime(d.last_seen_at) },
            { key: "traffic", header: t("client.traffic"), render: (d) => formatBytes(d.traffic_bytes) },
            {
              key: "state",
              header: "",
              render: (d) =>
                d.revoked_at ? <StatusBadge tone="danger" label={t("device.revoked")} /> : null,
            },
          ]}
        />
        <Link to={`/devices?q=c${client.id}-`} className="mt-2 inline-block text-accent">
          {t("nav.devices")} →
        </Link>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t("overview.payments")}>
          <DataTable
            rows={payments}
            rowKey={(p) => p.id}
            emptyText={t("overview.noPayments")}
            columns={[
              { key: "amount", header: t("payments.amount"), render: (p) => formatMoney(p.amount, p.currency) },
              { key: "status", header: t("clients.status"), render: (p) => p.status },
              { key: "at", header: t("payments.received"), render: (p) => formatDateTime(p.received_at) },
            ]}
          />
        </Card>
        <Card title={t("client.sessions")}>
          <DataTable
            rows={sessions}
            rowKey={(s) => s.id}
            columns={[
              { key: "user", header: "username", render: (s) => s.username },
              { key: "start", header: t("client.started"), render: (s) => formatDateTime(s.started_at) },
              { key: "ip", header: "IP", render: (s) => s.client_ip ?? "—" },
            ]}
          />
        </Card>
      </div>

      <Card title={t("client.trafficDaily")}>
        <DataTable<S<"DailyTrafficOut">>
          rows={query.data.traffic_daily}
          rowKey={(d) => d.day}
          columns={[
            { key: "day", header: t("client.day"), render: (d) => d.day },
            { key: "in", header: "↓", render: (d) => formatBytes(d.bytes_in) },
            { key: "out", header: "↑", render: (d) => formatBytes(d.bytes_out) },
          ]}
        />
      </Card>

      <ConfirmDialog
        open={dialog === "block"}
        title={t("client.blockTitle")}
        body={t("client.blockBody")}
        confirmLabel={t("client.block")}
        danger
        pending={block.isPending}
        onCancel={() => setDialog(null)}
        onConfirm={() =>
          block.mutate(undefined, {
            onSuccess: (r) => done(r.changed),
            onError: () => setDialog(null),
          })
        }
      />
      {dialog === "grant" && (
        <Modal title={t("client.grant")} onClose={() => setDialog(null)}>
          <GrantForm clientId={id} onDone={done} />
        </Modal>
      )}
      {dialog === "extend" && (
        <Modal title={t("client.extend")} onClose={() => setDialog(null)}>
          <ExtendForm clientId={id} onDone={done} />
        </Modal>
      )}
      {dialog === "issue" && <IssueDeviceDialog clientId={id} onClose={() => setDialog(null)} />}
    </div>
  );
}
