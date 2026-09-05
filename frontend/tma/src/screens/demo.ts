/**
 * Демонстрационные данные этапа 1. Единственное место, где живут числа.
 *
 * Цены и лимиты — выдуманные (решение C7.1): спецификация их не фиксирует,
 * тарифы приходят из таблицы `plans`. Не считать это прайсом.
 *
 * На этапе API этот файл удаляется целиком, а экраны получают те же поля
 * из хуков. Поэтому имена полей повторяют колонки БД, а не удобство экрана.
 */

export type Platform = "ios" | "android" | "windows" | "macos";

export interface DemoPlan {
  code: string;
  name: string;
  duration_days: number;
  device_limit: number;
  traffic_limit_bytes: number;
  price_amount: number; // минорные единицы: 29900 = 299,00 ₽
  currency: string;
  is_current: boolean;
}

export interface DemoDevice {
  id: string;
  name: string;
  platform: Platform;
  last_seen: string;
  traffic_used_bytes: number;
  username: string;
}

const GB = 1024 ** 3;

export const PLANS: DemoPlan[] = [
  {
    code: "basic",
    name: "Базовый",
    duration_days: 30,
    device_limit: 1,
    traffic_limit_bytes: 50 * GB,
    price_amount: 14900,
    currency: "RUB",
    is_current: false,
  },
  {
    code: "standard",
    name: "Стандарт",
    duration_days: 30,
    device_limit: 3,
    traffic_limit_bytes: 100 * GB,
    price_amount: 29900,
    currency: "RUB",
    is_current: true,
  },
  {
    code: "year",
    name: "Год",
    duration_days: 365,
    device_limit: 5,
    traffic_limit_bytes: 300 * GB,
    price_amount: 249000,
    currency: "RUB",
    is_current: false,
  },
];

export const SUBSCRIPTION = {
  plan_name: "Стандарт",
  days_left: 18,
  expires_at: "21.09.2026",
  auto_renew: true,
  price_amount: 29900,
  currency: "RUB",
  device_limit: 3,
  traffic_used_bytes: 40 * GB,
  traffic_limit_bytes: 100 * GB,
};

export const DEVICES: DemoDevice[] = [
  {
    id: "d1",
    name: "iPhone 15",
    platform: "ios",
    last_seen: "в сети",
    traffic_used_bytes: 12.4 * GB,
    username: "c42-d1",
  },
  {
    id: "d2",
    name: "MacBook Air",
    platform: "macos",
    last_seen: "2 дня назад",
    traffic_used_bytes: 27.8 * GB,
    username: "c42-d2",
  },
];

export const SECRET = {
  password: "7fQ2-mK9v-Lt41",
  ttl_seconds: 900,
  download_url: "https://example.invalid/key.p12",
};

export const ACCOUNT = {
  telegram_id: 418302774,
  support: "@ocmanager_help",
};

export const TRIAL = {
  days: 3,
  traffic_gb: 5,
  used_at: "12 августа",
};

/** Клиент VPN под каждую платформу — от него зависит инструкция. */
export const PLATFORM_INFO: Record<
  Platform,
  { label: string; client: string; badge: string; isApple: boolean }
> = {
  ios: {
    label: "iPhone, iPad",
    client: "AnyConnect",
    badge: "iOS",
    isApple: true,
  },
  android: {
    label: "Android",
    client: "OpenConnect",
    badge: "and",
    isApple: false,
  },
  windows: {
    label: "Windows",
    client: "OpenConnect GUI",
    badge: "win",
    isApple: false,
  },
  macos: { label: "macOS", client: "AnyConnect", badge: "mac", isApple: true },
};
