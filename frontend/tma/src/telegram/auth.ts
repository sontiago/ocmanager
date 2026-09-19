import { initDataRaw, initDataState } from "@telegram-apps/sdk-react";
import type { User } from "@telegram-apps/types";

export type Lang = "ru" | "en";
export type TelegramUser = User;

/** Вне Telegram и до init() сигналы SDK бросают — наружу это не выпускаем. */
function safe<T>(fn: () => T): T | undefined {
  try {
    return fn();
  } catch {
    return undefined;
  }
}

/** Сырая строка для заголовка Authorization: tma <initData>. */
export function getInitDataRaw(): string | undefined {
  return safe(() => initDataRaw());
}

export function getTelegramUser(): TelegramUser | undefined {
  return safe(() => initDataState())?.user;
}

/**
 * Ручного переключателя языка нет (решение C4): ru → ru, всё остальное → en.
 * Отсутствие языка = ru, это дефолт инсталляции.
 */
export function getTelegramLang(): Lang {
  const code = getTelegramUser()?.language_code;
  if (!code) return "ru";
  return code.toLowerCase().startsWith("ru") ? "ru" : "en";
}
