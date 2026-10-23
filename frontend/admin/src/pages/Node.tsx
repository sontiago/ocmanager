import { useState } from "react";
import { Link } from "react-router";
import {
  useNode,
  useNodeAction,
  useNodeProbe,
  useNodeSessions,
  useReconcile,
  type NodeAction,
} from "../api/hooks/node";
import { isApiError } from "../api/errors";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatBytes, formatDateTime, relativeTime } from "../lib/format";
import { useEventSource } from "../lib/useEventSource";
import { Card } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { DataTable } from "../ui/DataTable";
import { buttonClass, dangerButtonClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { StatusBadge, type Tone } from "../ui/StatusBadge";

const TONE: Record<string, Tone> = { online: "ok", degraded: "warn", offline: "danger" };
const MAX_LOG_LINES = 2000;
const TAIL = 200;

interface Pending {
  action: NodeAction;
  username?: string;
}

function Logs() {
  const { t } = useT();
  const [running, setRunning] = useState(false);
  const stream = useEventSource(running ? `/admin/node/logs?tail=${TAIL}` : null, {
    max: MAX_LOG_LINES,
  });

  return (
    <Card
      title={t("node.logs")}
      action={
        <div className="flex gap-2">
          {running && (
            <button className={buttonClass} onClick={stream.clear}>
              {t("node.logsClear")}
            </button>
          )}
          <button className={buttonClass} onClick={() => setRunning(!running)}>
            {running ? t("node.logsStop") : t("node.logsStart")}
          </button>
        </div>
      }
    >
      {stream.state === "error" && (
        <Notice tone="danger" text={stream.error ? t("node.unavailable") : t("node.logsLost")} />
      )}
      <pre className="mt-2 h-80 overflow-auto rounded-md border border-border bg-bg p-2 text-xs">
        {stream.lines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </pre>
    </Card>
  );
}

export function NodePage() {
  const { t } = useT();
  const node = useNode();
  const sessions = useNodeSessions();
  const probe = useNodeProbe();
  const action = useNodeAction();
  const reconcile = useReconcile();
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (node.error) return <Notice tone="danger" text={errorText(node.error, t("common.error"))} />;
  if (!node.data) return <p className="text-muted">{t("common.loading")}</p>;

  const { node: n, health } = node.data;
  const live: S<"HealthOut"> | null | undefined = probe.data ?? health;
  const noData = <span className="text-muted">{t("common.noData")}</span>;

  const ACTIONS: [NodeAction, string][] = [
    ["start", t("node.start")],
    ["stop", t("node.stop")],
    ["restart", t("node.restart")],
    ["reload", t("node.reload")],
  ];
  const title = pending
    ? pending.action === "disconnect_user"
      ? t("node.confirm.disconnect_user", { name: pending.username ?? "" })
      : t(`node.confirm.${pending.action}`)
    : "";

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{t("nav.node")}</h1>
      <Notice text={notice} />
      {action.error && <Notice tone="danger" text={errorText(action.error, t("common.error"))} />}

      <Card
        title={n.name}
        action={
          <div className="flex flex-wrap gap-2">
            <button className={buttonClass} disabled={probe.isPending} onClick={() => probe.mutate()}>
              {t("node.probe")}
            </button>
            <button
              className={buttonClass}
              disabled={reconcile.isPending}
              onClick={() => reconcile.mutate()}
            >
              {t("node.reconcile")}
            </button>
          </div>
        }
      >
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted">{t("node.state")}</dt>
          <dd>
            {live ? (
              <StatusBadge tone={TONE[live.state] ?? "neutral"} label={t(`node.state.${live.state}`)} />
            ) : (
              noData
            )}
          </dd>
          <dt className="text-muted">{t("node.container")}</dt>
          <dd>{live ? live.container_state : noData}</dd>
          <dt className="text-muted">{t("node.checked")}</dt>
          <dd>{live ? relativeTime(live.checked_at) : noData}</dd>
          <dt className="text-muted">{t("overview.reconcile")}</dt>
          <dd>{n.last_reconcile_at ? formatDateTime(n.last_reconcile_at) : noData}</dd>
          <dt className="text-muted">{t("node.host")}</dt>
          <dd>{n.public_host}</dd>
        </dl>
        {live?.error && <p className="mt-2 text-danger">{live.error}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {ACTIONS.map(([id, label]) => (
            <button
              key={id}
              className={id === "stop" ? dangerButtonClass : buttonClass}
              onClick={() => setPending({ action: id })}
            >
              {label}
            </button>
          ))}
        </div>
      </Card>

      {reconcile.error && <Notice tone="danger" text={errorText(reconcile.error, t("common.error"))} />}
      {reconcile.data && (
        <Card title={t("node.reconcileReport")}>
          {reconcile.data.error && <Notice tone="danger" text={reconcile.data.error} />}
          {reconcile.data.drifts.length === 0 && !reconcile.data.error && (
            <p className="text-ok">{t("node.noDrifts")}</p>
          )}
          <ul className="space-y-1">
            {reconcile.data.drifts.map((d, i) => (
              <li key={i}>
                <code>{d.kind}</code> <span className="text-muted">{JSON.stringify(d.details)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title={t("node.sessions")}>
        {sessions.error ? (
          <Notice
            tone="danger"
            text={isApiError(sessions.error) && sessions.error.status === 503 ? t("node.unavailable") : t("common.error")}
          />
        ) : (
          <DataTable
            rows={sessions.data}
            loading={sessions.isPending}
            rowKey={(s) => s.session_id}
            columns={[
              {
                key: "who",
                header: t("clients.name"),
                render: (s) =>
                  s.client_id === null ? (
                    <span className="text-muted">{s.username}</span>
                  ) : (
                    <Link to={`/clients/${s.client_id}`} className="text-accent">
                      {s.client_name} · {s.device_name}
                    </Link>
                  ),
              },
              { key: "ip", header: "IP", render: (s) => s.remote_ip },
              { key: "vpn", header: "VPN IP", render: (s) => s.vpn_ip ?? "—" },
              { key: "since", header: t("client.started"), render: (s) => relativeTime(s.connected_at) },
              {
                key: "traffic",
                header: t("client.traffic"),
                render: (s) => `↓ ${formatBytes(s.bytes_in)} ↑ ${formatBytes(s.bytes_out)}`,
              },
              {
                key: "act",
                header: "",
                className: "text-right",
                render: (s) => (
                  <button
                    className={buttonClass}
                    onClick={() => setPending({ action: "disconnect_user", username: s.username })}
                  >
                    {t("node.disconnect")}
                  </button>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Logs />

      <ConfirmDialog
        open={pending !== null}
        title={title}
        confirmLabel={
          pending?.action === "disconnect_user"
            ? t("node.disconnect")
            : (ACTIONS.find(([id]) => id === pending?.action)?.[1] ?? "")
        }
        danger={pending?.action === "stop" || pending?.action === "restart"}
        pending={action.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() =>
          pending &&
          action.mutate(
            { action: pending.action, ...(pending.username ? { username: pending.username } : {}) },
            {
              onSuccess: () => {
                setPending(null);
                setNotice(t("action.done"));
              },
              onError: () => setPending(null),
            },
          )
        }
      />
    </div>
  );
}
