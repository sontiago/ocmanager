import { miniApp, openLink, openTelegramLink } from "@telegram-apps/sdk-react";

/**
 * Внешняя ссылка: checkout платёжного провайдера, магазин приложений.
 * tryInstantView выключен намеренно: страница оплаты — не статья,
 * режим чтения Telegram её сломает.
 */
export function openExternal(url: string): void {
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
