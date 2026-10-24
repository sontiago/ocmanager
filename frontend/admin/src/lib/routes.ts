/** Проверка адреса мимо VPN. Зеркало backend (core/routes.py): итог всё равно проверяет сервер. */
export type RouteCheck = { ok: true; value: string } | { ok: false; reason: "format" | "default" | "special" };

const OCTET = /^(0|[1-9]\d{0,2})$/;

export function checkRoute(raw: string): RouteCheck {
  const text = raw.trim();
  const [addr, prefix, ...rest] = text.split("/");
  const parts = addr.split(".");
  if (rest.length > 0 || parts.length !== 4) return { ok: false, reason: "format" };
  if (!parts.every((p) => OCTET.test(p) && Number(p) <= 255)) return { ok: false, reason: "format" };
  let bits = 32;
  if (prefix !== undefined) {
    if (!/^\d{1,2}$/.test(prefix) || Number(prefix) > 32) return { ok: false, reason: "format" };
    bits = Number(prefix);
  }
  if (bits === 0) return { ok: false, reason: "default" };
  const [a, b] = parts.map(Number);
  if (a === 0 || a === 127 || a >= 224 || (a === 169 && b === 254)) return { ok: false, reason: "special" };
  return { ok: true, value: `${parts.map(Number).join(".")}/${bits}` };
}
