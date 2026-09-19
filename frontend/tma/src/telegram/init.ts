import {
  backButton,
  init,
  miniApp,
  restoreInitData,
  themeParams,
  viewport,
} from "@telegram-apps/sdk-react";

let initialized = false;

/**
 * Вызывается ровно один раз, до первого рендера.
 * Каждый mount обёрнут в проверку доступности: часть компонентов появилась
 * в поздних версиях Bot API, и на старом клиенте mount бросает исключение.
 */
export function initTelegram(): void {
  if (initialized) return;
  initialized = true;

  init();

  // ПОПРАВКА 1. init() только вешает обработчики событий. Разбор initData —
  // отдельный вызов; без него initDataRaw() и initDataState() пусты.
  restoreInitData();

  if (backButton.mount.isAvailable()) backButton.mount();

  // По решению C1 цвета берутся из своей палитры, но тема (светлая/тёмная)
  // читается отсюда: themeParams.isDark питает ThemeProvider.
  // bindCssVars не зовём — переменные --tg-theme-* в оформлении не участвуют.
  if (themeParams.mountSync.isAvailable()) themeParams.mountSync();

  if (miniApp.mountSync.isAvailable()) miniApp.mountSync();

  if (viewport.mount.isAvailable()) {
    void viewport.mount().then(() => {
      // ПОПРАВКА 3. По умолчанию SDK пишет --tg-viewport-safe-area-inset-top,
      // а index.css читает --tg-safe-area-inset-top (и --tg-content-...).
      // Переименовываем на стороне SDK, чтобы не трогать CSS.
      if (viewport.bindCssVars.isAvailable() && !viewport.isCssVarsBound()) {
        viewport.bindCssVars((key) => {
          if (key === "height") return "--tg-viewport-height";
          if (key === "stableHeight") return "--tg-viewport-stable-height";
          if (key === "width") return "--tg-viewport-width";
          // safeAreaInsetTop        → --tg-safe-area-inset-top
          // contentSafeAreaInsetTop → --tg-content-safe-area-inset-top
          return `--tg-${key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())}`;
        });
      }
      if (viewport.expand.isAvailable()) viewport.expand();
    });
  }
}
