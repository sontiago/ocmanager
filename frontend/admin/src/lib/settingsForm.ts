import type { S } from "../api/types";

const GB = 1024 ** 3;

type Runtime = S<"SettingsOut">["runtime"];

/** Поля формы настроек — строки; списки через запятую, трафик в ГБ. */
export interface SettingsForm {
  trial_days: string;
  trial_traffic_gb: string;
  default_lang: string;
  support_url: string;
  admin_chat_ids: string;
  expiry_reminder_days: string;
  traffic_retention_days: string;
  abuse_daily_traffic_gb: string;
  abuse_devices_per_ip: string;
}

/** Числа формы заполнены: пустое поле иначе ушло бы на сервер нулём или NaN. */
export function hasInvalidNumbers(f: SettingsForm): boolean {
  const single = [
    f.trial_days,
    f.trial_traffic_gb,
    f.traffic_retention_days,
    f.abuse_daily_traffic_gb,
    f.abuse_devices_per_ip,
  ];
  const lists = [f.admin_chat_ids, f.expiry_reminder_days];
  const bad = (s: string) => s.trim() === "" || !Number.isFinite(Number(s));
  return (
    single.some(bad) ||
    lists.some((l) => l.split(",").map((x) => x.trim()).filter(Boolean).some(bad))
  );
}

const list = (v: unknown) => (Array.isArray(v) ? v.join(", ") : "");
const ints = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number);

export function toForm(r: Runtime): SettingsForm {
  return {
    trial_days: String(r.trial_days),
    trial_traffic_gb: String(Number(r.trial_traffic_bytes) / GB),
    default_lang: String(r.default_lang),
    support_url: r.support_url ? String(r.support_url) : "",
    admin_chat_ids: list(r.admin_chat_ids),
    expiry_reminder_days: list(r.expiry_reminder_days),
    traffic_retention_days: String(r.traffic_retention_days),
    abuse_daily_traffic_gb: String(r.abuse_daily_traffic_gb),
    abuse_devices_per_ip: String(r.abuse_devices_per_ip),
  };
}

function values(f: SettingsForm): Record<string, unknown> {
  return {
    trial_days: Number(f.trial_days),
    trial_traffic_bytes: Math.round(Number(f.trial_traffic_gb) * GB),
    default_lang: f.default_lang,
    support_url: f.support_url.trim() || null,
    admin_chat_ids: ints(f.admin_chat_ids),
    expiry_reminder_days: ints(f.expiry_reminder_days),
    traffic_retention_days: Number(f.traffic_retention_days),
    abuse_daily_traffic_gb: Number(f.abuse_daily_traffic_gb),
    abuse_devices_per_ip: Number(f.abuse_devices_per_ip),
  };
}

/** Только изменившиеся ключи: PATCH /settings пишет ровно то, что передано. */
export function toPatch(original: Runtime, f: SettingsForm): Record<string, unknown> {
  const before = values(toForm(original));
  const after = values(f);
  const patch: Record<string, unknown> = {};
  for (const key of Object.keys(after)) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) patch[key] = after[key];
  }
  return patch;
}
