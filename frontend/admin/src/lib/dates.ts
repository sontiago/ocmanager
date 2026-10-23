/** Начало суток UTC для даты `YYYY-MM-DD`, сдвинутое на `plusDays`; пустое/неверное → undefined. */
export function dayStartUtc(day: string | undefined, plusDays = 0): string | undefined {
  if (!day) return undefined;
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return undefined;
  d.setUTCDate(d.getUTCDate() + plusDays);
  return d.toISOString();
}
