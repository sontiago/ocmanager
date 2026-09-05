const GB = 1024 ** 3;

/** Деньги: минорные единицы + валюта тарифа (решение C7.5).
 *  Разделитель разрядов отдаём Intl, узкий пробел прототипа
 *  не воспроизводим (решение C7.6). */
export function formatMoney(minorUnits: number, currency: string): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: minorUnits % 100 === 0 ? 0 : 2,
  }).format(minorUnits / 100);
}

export function formatGb(bytes: number): string {
  return (bytes / GB).toFixed(1).replace(".", ",");
}

/** Лимит тарифа — целым: «100», «50». Величина договорная, дробной не бывает. */
export function formatGbWhole(bytes: number): string {
  return String(Math.round(bytes / GB));
}

/** 900 → «15:00». tabular-nums в вёрстке не даёт цифрам скакать. */
export function formatCountdown(totalSeconds: number): string {
  const mm = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const ss = String(totalSeconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
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
