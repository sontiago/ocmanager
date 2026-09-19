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

/** Заголовок в шапке.*/
export function titleFor(pathname: string): string {
  if (pathname === ROUTES.home) return "Моя подписка";
  if (pathname === ROUTES.plans) return "Тарифы";
  if (pathname.endsWith("/checkout")) return "Оплата";
  if (pathname === ROUTES.deviceNew) return "Новое устройство";
  if (pathname.startsWith("/devices/key/")) return "Ключ подключения";
  if (pathname.startsWith("/devices/guide/")) return "Подключение";
  if (pathname === ROUTES.devices) return "Устройства";
  if (pathname === ROUTES.renew) return "Продление";
  if (pathname === ROUTES.account) return "Аккаунт";
  if (pathname === ROUTES.onboarding) return "ocmanager";
  if (pathname === "/error") return "Ошибка";
  return "";
}
