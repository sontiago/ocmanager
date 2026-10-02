import {
  emitEvent,
  mockTelegramEnv,
  retrieveRawLaunchParams,
} from "@telegram-apps/sdk-react";

/** Подпись, по которой подделку отличают от настоящих параметров запуска. */
const MOCK_HASH = "dev-mock-hash";

/**
 * Настоящие параметры запуска уже есть (открыто из Telegram, пусть и через туннель к dev-серверу).
 * mockTelegramEnv каждый раз записывает свои, фальшивые, в хранилище сессии; а после перезагрузки
 * страницы хэша `#tgWebAppData` в адресе уже нет, и SDK берёт параметры из хранилища — то есть
 * подделку: бэкенд отвечает 401 «bad hash». Поэтому поверх настоящих мок не включаем.
 */
export function hasRealLaunchParams(): boolean {
  try {
    return !retrieveRawLaunchParams().includes(MOCK_HASH);
  } catch {
    return false; // параметров нет вовсе — обычный браузер
  }
}

/**
 * ВНИМАНИЕ. Здесь подделывается окружение Telegram, включая подпись initData.
 * Подпись заведомо недействительная. Бэкенд обязан принимать её ТОЛЬКО при
 * включённом TMA_ALLOW_DEV_INITDATA=true, который в production выключен.
 */
const user = {
  id: 99281932,
  first_name: "Иван",
  last_name: "Петров",
  username: "ivan",
  language_code: "ru",
  is_premium: false,
  allows_write_to_pm: true,
};

// tgWebAppData обязан быть СЫРОЙ строкой, а не объектом: SDK разбирает её
// тем же кодом, что и настоящую, и ей же подписывается запрос к бэкенду.
const initDataRaw = new URLSearchParams([
  ["user", JSON.stringify(user)],
  ["auth_date", Math.floor(Date.now() / 1000).toString()],
  ["chat_instance", "-1234567890123456789"],
  ["chat_type", "private"],
  ["signature", "dev-mock-signature"],
  ["hash", MOCK_HASH],
]).toString();

const themeParams = {
  accent_text_color: "#168acd",
  bg_color: "#ffffff",
  button_color: "#40a7e3",
  button_text_color: "#ffffff",
  destructive_text_color: "#d14e4e",
  hint_color: "#999999",
  link_color: "#168acd",
  secondary_bg_color: "#f1f1f1",
  section_bg_color: "#ffffff",
  section_separator_color: "#e7e7e7",
  subtitle_text_color: "#999999",
  text_color: "#000000",
} as const;

if (!hasRealLaunchParams()) {
  mockTelegramEnv({
    launchParams: {
      tgWebAppVersion: "8.0",
      tgWebAppPlatform: "tdesktop",
      tgWebAppThemeParams: themeParams,
      tgWebAppData: initDataRaw,
    },

    // Часть методов SDK — это запрос к клиенту с ожиданием ответного события.
    // В браузере клиента нет, и viewport.mount() висит в isMounting вечно:
    // не срабатывают ни bindCssVars(), ни expand(). Отвечаем за клиента сами.
    onEvent([name]) {
      switch (name) {
        case "web_app_request_viewport":
          return emitEvent("viewport_changed", {
            height: window.innerHeight,
            width: window.innerWidth,
            is_expanded: true,
            is_state_stable: true,
          });
        case "web_app_request_safe_area":
          return emitEvent("safe_area_changed", {
            top: 0,
            bottom: 0,
            left: 0,
            right: 0,
          });
        case "web_app_request_content_safe_area":
          // Поставь top: 56, чтобы увидеть в браузере реальный отступ под
          // шапкой клиента — так это выглядит на телефоне.
          return emitEvent("content_safe_area_changed", {
            top: 0,
            bottom: 0,
            left: 0,
            right: 0,
          });
        case "web_app_request_theme":
          return emitEvent("theme_changed", { theme_params: themeParams });
      }
    },
  });

  console.warn(
    "[tma] окружение Telegram замокано — только для разработки, в production этот модуль не собирается",
  );
} else {
  console.info("[tma] открыто из Telegram: мок окружения не включается");
}
