let lang: "ru" | "en" = "ru";

/** Язык форматирования; ставится провайдером i18n. */
export function setFormatLang(next: "ru" | "en"): void {
  lang = next;
}

const BYTE_UNITS = {
  ru: ["Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"],
  en: ["B", "KB", "MB", "GB", "TB", "PB"],
};

export function formatBytes(bytes: number): string {
  const units = BYTE_UNITS[lang];
  let value = Math.max(0, bytes);
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const digits = i > 0 && value < 10 ? 1 : 0;
  return `${new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(value)} ${units[i]}`;
}

/** `minor` — минорные единицы (копейки, центы). */
export function formatMoney(minor: number, currency: string): string {
  const major = minor / 100;
  try {
    return new Intl.NumberFormat(lang, { style: "currency", currency }).format(major);
  } catch {
    return `${new Intl.NumberFormat(lang).format(major)} ${currency}`;
  }
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function formatDuration(sec: number): string {
  const [h, m, s] = lang === "ru" ? ["ч", "м", "с"] : ["h", "m", "s"];
  const hours = Math.floor(sec / 3600);
  const minutes = Math.floor((sec % 3600) / 60);
  if (hours > 0) return `${hours}${h} ${minutes}${m}`;
  if (minutes > 0) return `${minutes}${m}`;
  return `${Math.floor(sec)}${s}`;
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diffSec = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  const abs = Math.abs(diffSec);
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  return rtf.format(Math.round(diffSec / 86400), "day");
}
