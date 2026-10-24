import { useState, type FormEvent } from "react";
import { useSettings, usePatchSettings } from "../api/hooks/settings";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { hasInvalidNumbers, toForm, toPatch, type SettingsForm } from "../lib/settingsForm";
import { Card } from "../ui/Card";
import { Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Notice } from "../ui/Notice";
import { BypassRoutes } from "./BypassRoutes";

function Form({ settings }: { settings: S<"SettingsOut"> }) {
  const { t } = useT();
  const patch = usePatchSettings();
  const [form, setForm] = useState<SettingsForm>(toForm(settings.runtime));
  const [notice, setNotice] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  // С чем сравнивать: то, из чего форма была заполнена, а не последний ответ сервера. Иначе чужая
  // правка другого поля, пришедшая при обновлении, ушла бы обратно старым значением.
  const [baseline, setBaseline] = useState(settings.runtime);

  const bind = (key: keyof SettingsForm) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    setInvalid(hasInvalidNumbers(form));
    if (hasInvalidNumbers(form)) return;
    const changes = toPatch(baseline, form);
    if (Object.keys(changes).length === 0) return;
    patch.mutate(changes, {
      onSuccess: (saved) => {
        setBaseline(saved.runtime);
        setForm(toForm(saved.runtime));
        setNotice(t("settings.saved"));
      },
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label={t("settings.trialDays")}>
        <input className={inputClass} type="number" {...bind("trial_days")} />
      </Field>
      <Field label={t("settings.trialTrafficGb")}>
        <input className={inputClass} type="number" step="any" {...bind("trial_traffic_gb")} />
      </Field>
      <Field label={t("settings.defaultLang")}>
        <select className={inputClass} {...bind("default_lang")}>
          <option value="ru">ru</option>
          <option value="en">en</option>
        </select>
      </Field>
      <Field label={t("settings.supportUrl")}>
        <input className={inputClass} {...bind("support_url")} />
      </Field>
      <Field label={t("settings.adminChats")}>
        <input className={inputClass} {...bind("admin_chat_ids")} />
      </Field>
      <Field label={t("settings.reminderDays")}>
        <input className={inputClass} {...bind("expiry_reminder_days")} />
      </Field>
      <Field label={t("settings.retentionDays")}>
        <input className={inputClass} type="number" {...bind("traffic_retention_days")} />
      </Field>
      <Field label={t("settings.abuseTraffic")}>
        <input className={inputClass} type="number" min={0} {...bind("abuse_daily_traffic_gb")} />
      </Field>
      <Field label={t("settings.abuseDevices")}>
        <input className={inputClass} type="number" min={0} {...bind("abuse_devices_per_ip")} />
      </Field>
      {invalid && <Notice tone="danger" text={t("settings.fillNumbers")} />}
      {patch.error && <Notice tone="danger" text={errorText(patch.error, t)} />}
      <Notice text={notice} />
      <button type="submit" className={primaryButtonClass} disabled={patch.isPending}>
        {t("common.save")}
      </button>
    </form>
  );
}

export function SettingsPage() {
  const { t } = useT();
  const query = useSettings();
  if (query.error) return <Notice tone="danger" text={t("common.error")} />;
  if (!query.data) return <p className="text-muted">{t("common.loading")}</p>;
  const env = query.data.environment;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-normal">{t("nav.settings")}</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t("settings.runtime")}>
          <Form settings={query.data} />
        </Card>
        <BypassRoutes saved={(query.data.runtime.bypass_routes as string[] | undefined) ?? []} />
        <Card title={t("settings.environment")}>
          <p className="mb-2 text-muted">{t("settings.environmentHint")}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">env</dt>
            <dd>{env.env}</dd>
            <dt className="text-muted">VPN host</dt>
            <dd>{env.vpn_host}</dd>
            <dt className="text-muted">ocserv</dt>
            <dd>{env.ocserv_container}</dd>
            <dt className="text-muted">{t("settings.version")}</dt>
            <dd>{env.version}</dd>
          </dl>
        </Card>
      </div>
    </div>
  );
}
