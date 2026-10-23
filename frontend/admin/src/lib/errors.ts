import { isApiError } from "../api/errors";

/** Текст ошибки для пользователя: сообщение API, если оно есть, иначе запасной текст. */
export function errorText(err: unknown, fallback: string): string {
  if (isApiError(err) && err.message && err.message !== err.code) return err.message;
  return fallback;
}
