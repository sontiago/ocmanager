import { isApiError } from "../api/errors";

type T = (key: string, vars?: Record<string, string | number>) => string;

/** Коды, у которых подробность сервера называет поле или причину: её стоит показать целиком. */
const KEEPS_DETAIL = new Set(["validation_error", "conflict"]);

/**
 * Текст ошибки для человека на языке интерфейса. Сообщения сервера английские и написаны для
 * логов, поэтому по умолчанию показывается перевод кода; серверная подробность добавляется
 * только там, где она названа полем или причиной (`validation_error`, `conflict`).
 */
export function errorText(err: unknown, t: T): string {
  const generic = t("common.error");
  if (!isApiError(err)) return generic;

  const http = /^http_(\d{3})$/.exec(err.code);
  const code = http ? (Number(http[1]) >= 500 ? "internal" : "") : err.code;
  const key = `apiError.${code}`;
  const base = code ? t(key) : key;
  if (!code || base === key) return generic;

  const detail = err.message;
  return KEEPS_DETAIL.has(code) && detail && detail !== err.code ? `${base}: ${detail}` : base;
}
