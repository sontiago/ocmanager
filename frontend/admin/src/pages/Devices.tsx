import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useDevices, useDeviceSessions, useRevokeDevice } from "../api/hooks/devices";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatBytes, formatDateTime, formatDuration } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { useUrlFilters } from "../lib/useUrlFilters";
import { DataTable, type Column } from "../ui/DataTable";
import { buttonClass, dangerButtonClass, Field, inputClass } from "../ui/Field";
import { Modal } from "../ui/Modal";
import { Notice } from "../ui/Notice";
import { Pagination } from "../ui/Pagination";
import { StatusBadge } from "../ui/StatusBadge";

const KEYS = ["q", "platform", "revoked", "online"] as const;
const PLATFORMS = ["ios", "android", "windows", "macos", "linux"];

function Sessions({ id }: { id: number }) {
  const { t } = useT();
  const { data, isPending } = useDeviceSessions(id);
  if (isPending) return <p className="text-muted">{t("common.loading")}</p>;
  return (
    <ul className="mt-2 space-y-1 text-xs">
      {data?.items.map((s) => (
        <li key={s.id} className="flex flex-wrap gap-x-4">
          <span>{formatDateTime(s.started_at)}</span>
          <span>{formatDuration(s.duration_sec)}</span>
          <span>{s.client_ip ?? "—"}</span>
          <span>
            ↓ {formatBytes(s.bytes_in)} ↑ {formatBytes(s.bytes_out)}
          </span>
        </li>
      ))}
      {data?.items.length === 0 && <li className="text-muted">{t("common.empty")}</li>}
    </ul>
  );
}

function RevokeDialog({ device, onClose }: { device: S<"DeviceRow">; onClose(): void }) {
  const { t } = useT();
  const revoke = useRevokeDevice();
  const [reason, setReason] = useState("");
  const clean = reason.trim();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (clean) revoke.mutate({ id: device.id, reason: clean }, { onSuccess: onClose });
  }
  return (
    <Modal title={t("devices.revokeTitle", { name: device.name })} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-muted">{t("devices.revokeBody")}</p>
        <Field label={t("devices.reason")}>
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
        {revoke.error && <Notice tone="danger" text={errorText(revoke.error, t("common.error"))} />}
        <div className="flex justify-end gap-2">
          <button type="button" className={buttonClass} onClick={onClose} disabled={revoke.isPending}>
            {t("common.cancel")}
          </button>
          <button type="submit" className={dangerButtonClass} disabled={!clean || revoke.isPending}>
            {t("devices.revoke")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const triState = (v: string | undefined) => (v === undefined ? undefined : v === "true");

export function DevicesPage() {
  const { t } = useT();
  const { values, set, limit, offset, setOffset } = useUrlFilters(KEYS);
  const [text, setText] = useState(values.q ?? "");
  const debounced = useDebounced(text, 300);
  useEffect(() => {
    if (debounced !== (values.q ?? "")) set({ q: debounced });
  }, [debounced]);

  const query = useDevices({
    q: values.q,
    platform: values.platform,
    revoked: triState(values.revoked),
    online: triState(values.online),
    limit,
    offset,
  });
  const [expanded, setExpanded] = useState<number | null>(null);
  const [toRevoke, setToRevoke] = useState<S<"DeviceRow"> | null>(null);

  const columns: Column<S<"DeviceRow">>[] = [
    {
      key: "device",
      header: t("device.name"),
      render: (d) => (
        <div>
          <div>
            {d.name} <span className="text-muted">{d.username}</span>
          </div>
          {expanded === d.id && <Sessions id={d.id} />}
        </div>
      ),
    },
    {
      key: "client",
      header: t("clients.name"),
      render: (d) => (
        <Link to={`/clients/${d.client_id}`} className="text-accent">
          {d.client_name}
        </Link>
      ),
    },
    { key: "platform", header: t("device.platform"), render: (d) => d.platform },
    { key: "seen", header: t("device.lastSeen"), render: (d) => formatDateTime(d.last_seen_at) },
    {
      key: "online",
      header: t("devices.online"),
      render: (d) =>
        d.revoked_at ? (
          <StatusBadge tone="danger" label={t("device.revoked")} />
        ) : d.is_online === null ? (
          <span className="text-muted">{t("common.noData")}</span>
        ) : (
          <StatusBadge tone={d.is_online ? "ok" : "neutral"} label={d.is_online ? t("devices.on") : t("devices.off")} />
        ),
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (d) => (
        <span className="flex justify-end gap-2">
          <button className={buttonClass} onClick={() => setExpanded(expanded === d.id ? null : d.id)}>
            {t("devices.sessions")}
          </button>
          {!d.revoked_at && (
            <button className={buttonClass} onClick={() => setToRevoke(d)}>
              {t("devices.revoke")}
            </button>
          )}
        </span>
      ),
    },
  ];

  const triOptions = (
    <>
      <option value="">{t("common.all")}</option>
      <option value="true">{t("common.yes")}</option>
      <option value="false">{t("common.no")}</option>
    </>
  );

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t("nav.devices")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("clients.search")}>
          <input className={inputClass} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label={t("device.platform")}>
          <select className={inputClass} value={values.platform ?? ""} onChange={(e) => set({ platform: e.target.value || undefined })}>
            <option value="">{t("common.all")}</option>
            {PLATFORMS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        <Field label={t("devices.revokedFilter")}>
          <select className={inputClass} value={values.revoked ?? ""} onChange={(e) => set({ revoked: e.target.value || undefined })}>
            {triOptions}
          </select>
        </Field>
        <Field label={t("devices.online")}>
          <select className={inputClass} value={values.online ?? ""} onChange={(e) => set({ online: e.target.value || undefined })}>
            {triOptions}
          </select>
        </Field>
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.items}
        rowKey={(d) => d.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
      />
      {query.data && <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />}
      {toRevoke && <RevokeDialog device={toRevoke} onClose={() => setToRevoke(null)} />}
    </div>
  );
}
