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
