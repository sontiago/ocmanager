import type { Lang } from "../telegram/auth";

const LOCALES: Record<Lang, string> = { ru: "ru-RU", en: "en-US" };

/**
 * Единицы держим здесь, а не в i18n-каталогах: это формат числа, а не текст
 * интерфейса. Intl style:'unit' даёт нестабильный вывод между версиями ICU.
 */
const BYTE_UNITS: Record<Lang, readonly string[]> = {
  ru: ["Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"],
  en: ["B", "KB", "MB", "GB", "TB", "PB"],
};

export function formatBytes(bytes: number, lang: Lang): string {
  const units = BYTE_UNITS[lang];
  if (!Number.isFinite(bytes) || bytes <= 0) return `0 ${units[0]}`;

  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }

  const formatted = new Intl.NumberFormat(LOCALES[lang], {
    maximumFractionDigits: index === 0 ? 0 : 1,
  }).format(value);

  return `${formatted} ${units[index]}`;
}

export function formatMoney(
  minorUnits: number,
  currency: string,
  lang: Lang,
): string {
  // Telegram Stars не входят в ISO 4217 — Intl на них бросает RangeError.
  if (currency === "XTR") {
    return `${new Intl.NumberFormat(LOCALES[lang]).format(minorUnits)} ⭐`;
  }

  const major = minorUnits / 100;
  try {
    return new Intl.NumberFormat(LOCALES[lang], {
      style: "currency",
      currency,
      // 299 ₽ вместо 299,00 ₽, но 299,50 ₽ сохраняется
      minimumFractionDigits: Number.isInteger(major) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(major);
  } catch {
    return `${new Intl.NumberFormat(LOCALES[lang]).format(major)} ${currency}`;
  }
}

export function formatDate(iso: string, lang: Lang): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  return new Intl.DateTimeFormat(LOCALES[lang], {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(ms));
}

/**
 * «2 часа назад», «вчера», «3 дня назад» — время последнего подключения.
 * Старше месяца переходит на дату: «давно» интереснее точности до дня.
 * `now` параметром, а не Date.now() внутри, — иначе тест недетерминирован.
 */
export function formatRelative(
  iso: string,
  lang: Lang,
  now: number = Date.now(),
): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";

  const diff = ms - now; // отрицательное — в прошлом
  // numeric:"auto" даёт «вчера» вместо «1 день назад»
  const rtf = new Intl.RelativeTimeFormat(LOCALES[lang], { numeric: "auto" });

  const minutes = Math.round(diff / 60_000);
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");

  const hours = Math.round(diff / 3_600_000);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");

  const days = Math.round(diff / 86_400_000);
  if (Math.abs(days) < 30) return rtf.format(days, "day");

  return formatDate(iso, lang);
}

/** Обратный отсчёт mm:ss для TTL одноразовой ссылки. */
export function formatCountdown(msLeft: number): string {
  const total = Math.max(0, Math.floor(msLeft / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

// ─── Временное: помощники экранов-заглушек Фазы 0 ────────────────────────────
// Экраны Фазы 3 перейдут на formatBytes и tPlural из i18n; тогда этот блок
// удаляется целиком.

const GB = 1024 ** 3;

export function formatGb(bytes: number): string {
  return (bytes / GB).toFixed(1).replace(".", ",");
}

/** Лимит тарифа — целым: «100», «50». Величина договорная, дробной не бывает. */
export function formatGbWhole(bytes: number): string {
  return String(Math.round(bytes / GB));
}

/** Русские склонения: 1 день / 2 дня / 5 дней. */
export function plural(
  n: number,
  one: string,
  few: string,
  many: string,
): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
