import { useState, type FormEvent } from "react";
import { useIssueDevice } from "../api/hooks/clients";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { formatDateTime } from "../lib/format";
import { buttonClass, Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Modal } from "../ui/Modal";
import { Notice } from "../ui/Notice";

const PLATFORMS = ["ios", "android", "windows", "macos", "linux"] as const;

/** Пароль .p12 показывается один раз: после закрытия его нет ни в DOM, ни в кэше мутаций. */
export function IssueDeviceDialog({ clientId, onClose }: { clientId: number; onClose(): void }) {
  const { t } = useT();
  const issue = useIssueDevice(clientId);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<(typeof PLATFORMS)[number]>("ios");

  function close() {
    issue.reset();
    onClose();
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    issue.mutate({ name: name.trim(), platform });
  }

  if (issue.data) {
    const r = issue.data;
    return (
      <Modal title={t("device.issued")} onClose={close}>
        <div className="space-y-3">
          <p className="text-muted">{t("device.issuedHint")}</p>
          <Field label={t("device.p12Password")}>
            <code className="block rounded-md border border-border p-2 select-all">
              {r.p12_password}
            </code>
          </Field>
          <a className="block text-accent" href={r.download_path}>
            {t("device.download")} ({t("device.validUntil", { at: formatDateTime(r.download_expires_at) })})
          </a>
          <div className="flex justify-end">
            <button type="button" className={primaryButtonClass} onClick={close}>
              {t("common.close")}
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={t("device.issue")} onClose={close}>
      <form onSubmit={submit} className="space-y-3">
        <Field label={t("device.name")}>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label={t("device.platform")}>
          <select
            className={inputClass}
            value={platform}
            onChange={(e) => setPlatform(e.target.value as (typeof PLATFORMS)[number])}
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
        {issue.error && <Notice tone="danger" text={errorText(issue.error, t("common.error"))} />}
        <div className="flex justify-end gap-2">
          <button type="button" className={buttonClass} onClick={close}>
            {t("common.cancel")}
          </button>
          <button type="submit" className={primaryButtonClass} disabled={issue.isPending}>
            {t("device.issueSubmit")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
