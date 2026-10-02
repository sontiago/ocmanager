import { miniApp, openLink, openTelegramLink } from "@telegram-apps/sdk-react";

const TELEGRAM_HOSTS = new Set(["t.me", "telegram.me"]);

function isTelegramLink(url: string): boolean {
  try {
    const { protocol, hostname } = new URL(url);
    return protocol === "https:" && TELEGRAM_HOSTS.has(hostname);
  } catch {
    return false;
  }
}

/**
 * Внешняя ссылка: checkout платёжного провайдера, магазин приложений.
 * tryInstantView выключен намеренно: страница оплаты — не статья,
 * режим чтения Telegram её сломает.
 */
export function openExternal(url: string): void {
  // Ссылка Tribute вида https://t.me/tribute/app?startapp=… — это Telegram, а не сайт: через
  // openLink она уходит в браузер и до оплаты не доходит. Такие ссылки открывает сам клиент.
  if (isTelegramLink(url)) {
    openInTelegram(url);
    return;
  }
  if (openLink.isAvailable()) {
    openLink(url, { tryInstantView: false });
    return;
  }
  // Запуск в обычном браузере (разработка, отладка). noopener обязателен:
  // без него новая вкладка получает доступ к window.opener исходной
  // страницы и может её перенаправить.
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Ссылка t.me — открывается внутри Telegram, без выхода в браузер. */
export function openInTelegram(url: string): void {
  if (openTelegramLink.isAvailable()) {
    openTelegramLink(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Закрывает мини-приложение. Вне Telegram — тихо ничего не делает. */
export function closeApp(): void {
  if (miniApp.close.isAvailable()) miniApp.close();
}
