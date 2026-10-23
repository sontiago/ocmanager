import { useState, type FormEvent } from "react";
import {
  useAdminSessions,
  useChangePassword,
  useCloseSession,
  useTotpConfirm,
  useTotpDisable,
  useTotpSetup,
} from "../api/hooks/account";
import type { S } from "../api/types";
import { useSession } from "../api/session";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatDateTime } from "../lib/format";
import { Card } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { DataTable } from "../ui/DataTable";
import { buttonClass, Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { StatusBadge } from "../ui/StatusBadge";

function PasswordCard() {
  const { t } = useT();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setDone(t("profile.passwordChanged"));
        },
      },
    );
  }
  return (
    <Card title={t("profile.password")}>
      <form onSubmit={submit} className="space-y-3">
        <Field label={t("profile.currentPassword")}>
          <input className={inputClass} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label={t("profile.newPassword")}>
          <input className={inputClass} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </Field>
        {change.error && <Notice tone="danger" text={errorText(change.error, t)} />}
        <Notice text={done} />
        <button type="submit" className={primaryButtonClass} disabled={change.isPending}>
          {t("profile.changePassword")}
        </button>
      </form>
    </Card>
  );
}

function TotpCard() {
  const { t } = useT();
  const { admin, refresh } = useSession();
  const setup = useTotpSetup();
  const confirm = useTotpConfirm();
  const disable = useTotpDisable();
  const [code, setCode] = useState("");
  const enabled = admin?.totp_enabled ?? false;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const run = enabled ? disable : confirm;
    run.mutate(code, {
      onSuccess: async () => {
        setCode("");
        setup.reset();
        await refresh();
      },
    });
  }
  const failing = enabled ? disable.error : confirm.error;

  return (
    <Card title={t("profile.totp")}>
      {!enabled && !setup.data && (
        <button className={buttonClass} disabled={setup.isPending} onClick={() => setup.mutate()}>
          {t("profile.totpEnable")}
        </button>
      )}
      {setup.error && <Notice tone="danger" text={errorText(setup.error, t)} />}
      {!enabled && setup.data && (
        <div className="mb-3 space-y-1">
          <p className="text-muted">{t("profile.totpHint")}</p>
          <code className="block select-all rounded-md border border-border p-2">{setup.data.secret}</code>
          <code className="block select-all break-all rounded-md border border-border p-2 text-xs">
            {setup.data.otpauth_uri}
          </code>
        </div>
      )}
      {(enabled || setup.data) && (
        <form onSubmit={submit} className="space-y-3">
          <Field label={t("login.totp")}>
            <input className={inputClass} inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} required />
          </Field>
          {failing && <Notice tone="danger" text={errorText(failing, t)} />}
          <button type="submit" className={enabled ? buttonClass : primaryButtonClass}>
            {enabled ? t("profile.totpDisable") : t("profile.totpConfirm")}
          </button>
        </form>
      )}
    </Card>
  );
}

function SessionsCard() {
  const { t } = useT();
  const query = useAdminSessions();
  const close = useCloseSession();
  const [target, setTarget] = useState<S<"SessionOut"> | null>(null);

  return (
    <Card title={t("profile.sessions")}>
      <DataTable
        rows={query.data}
        rowKey={(s) => s.id}
        loading={query.isPending}
        error={query.error ? t("common.error") : null}
        columns={[
          { key: "ua", header: t("profile.device"), render: (s) => s.user_agent ?? "—" },
          { key: "ip", header: "IP", render: (s) => s.ip ?? "—" },
          { key: "seen", header: t("device.lastSeen"), render: (s) => formatDateTime(s.last_seen_at) },
          {
            key: "act",
            header: "",
            className: "text-right",
            render: (s) =>
              s.current ? (
                <StatusBadge tone="ok" label={t("profile.current")} />
              ) : (
                <button className={buttonClass} onClick={() => setTarget(s)}>
                  {t("profile.closeSession")}
                </button>
              ),
          },
        ]}
      />
      {close.error && <Notice tone="danger" text={errorText(close.error, t)} />}
      <ConfirmDialog
        open={target !== null}
        title={t("profile.closeSession")}
        body={target?.user_agent ?? undefined}
        confirmLabel={t("profile.closeSession")}
        danger
        pending={close.isPending}
        onCancel={() => setTarget(null)}
        onConfirm={() => target && close.mutate(target.id, { onSuccess: () => setTarget(null) })}
      />
    </Card>
  );
}

export function ProfilePage() {
  const { t } = useT();
  const { admin } = useSession();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-normal">
        {t("nav.profile")} <span className="text-muted">{admin?.username}</span>
      </h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PasswordCard />
        <TotpCard />
      </div>
      <SessionsCard />
    </div>
  );
}
