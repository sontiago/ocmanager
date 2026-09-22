import type { MessageKey } from "../i18n/ru";

export const ROUTES = {
  home: "/",
  plans: "/plans",
  checkout: (planCode: string) => `/plans/${planCode}/checkout`,
  devices: "/devices",
  deviceNew: "/devices/new",
  deviceKey: (platform: string) => `/devices/key/${platform}`,
  deviceGuide: (platform: string) => `/devices/guide/${platform}`,
  renew: "/renew",
  account: "/account",
  onboarding: "/onboarding",
} as const;

/** Шаблоны для <Route path>. Функции выше строят конкретные адреса,
 *  эти строки описывают форму. */
export const PATHS = {
  home: "/",
  plans: "/plans",
  checkout: "/plans/:planCode/checkout",
  devices: "/devices",
  deviceNew: "/devices/new",
  deviceKey: "/devices/key/:platform",
  deviceGuide: "/devices/guide/:platform",
  renew: "/renew",
  account: "/account",
  onboarding: "/onboarding",
} as const;

/**
 * Маршруты, на которых виден таб-бар. Это ровно четыре раздела.
 * На всех остальных экранах он скрыт: вложенный экран занимает окно
 * целиком — так устроены мини-приложения, и так человек понимает,
 * что находится «внутри», а не в разделе.
 */
const TAB_ROUTES: string[] = [
  ROUTES.home,
  ROUTES.devices,
  ROUTES.plans,
  ROUTES.account,
];

export function hasTabBar(pathname: string): boolean {
  return TAB_ROUTES.includes(pathname);
}

/** Ключ заголовка в шапке; null — заголовка у экрана нет. */
export function titleFor(pathname: string): MessageKey | null {
  if (pathname === ROUTES.home) return "title.home";
  if (pathname === ROUTES.plans) return "title.plans";
  if (pathname.endsWith("/checkout")) return "title.checkout";
  if (pathname === ROUTES.deviceNew) return "title.deviceNew";
  if (pathname.startsWith("/devices/key/")) return "title.deviceKey";
  if (pathname.startsWith("/devices/guide/")) return "title.deviceGuide";
  if (pathname === ROUTES.devices) return "title.devices";
  if (pathname === ROUTES.renew) return "title.renew";
  if (pathname === ROUTES.account) return "title.account";
  if (pathname === ROUTES.onboarding) return "title.onboarding";
  return null;
}

/**
 * Куда уводит нативная кнопка «Назад» Telegram; null — экран корневой,
 * кнопку не показываем. Путь задан явно, а не через history.back():
 * после возврата из внешней оплаты история браузера непредсказуема.
 */
export function backTargetFor(pathname: string): string | null {
  if (hasTabBar(pathname)) return null;
  if (pathname === ROUTES.onboarding) return null;
  if (pathname.endsWith("/checkout")) return ROUTES.plans;
  if (pathname.startsWith("/devices/")) return ROUTES.devices;
  return ROUTES.home;
}
