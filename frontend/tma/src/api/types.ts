/** Идентификатор клиента, каким его видит TMA. */
export interface Me {
  telegram_id: number;
  first_name: string;
  username: string | null;
  lang: "ru" | "en";
  is_blocked: boolean;
  trial_available: boolean;
}

export interface Plan {
  code: string;
  /** Уже локализовано бэкендом под язык клиента (C7.3): в каталог i18n не попадает. */
  name: string;
  /**
   * Необязательный маркетинговый текст (C7.4). Строку «30 дней · 3 устройства ·
   * 100 ГБ» фронт собирает сам из duration_days / device_limit /
   * traffic_limit_bytes со склонениями из plural.ts — иначе склонения пришлось
   * бы дублировать в базе для каждого тарифа и каждого языка.
   */
  description?: string | null;
  duration_days: number;
  device_limit: number;
  /** null = безлимит. */
  traffic_limit_bytes: number | null;
  speed_limit_kbps: number | null;
  /** Целое в минорных единицах: 49900 = 499,00 ₽. */
  price_amount: number;
  /** ISO 4217: RUB, USD, XTR (Telegram Stars). */
  currency: string;
  /** Скрытый системный тариф пробного периода. */
  is_trial: boolean;
  sort_order: number;
}

export type SubscriptionStatus =
  | "pending_payment"
  | "trial"
  | "active"
  | "expired"
  | "exhausted"
  | "cancelled"
  | "blocked";

export interface Subscription {
  id: string;
  plan: Plan;
  status: SubscriptionStatus;
  /** ISO 8601 UTC. */
  started_at: string | null;
  expires_at: string | null;
  traffic_used_bytes: number;
  /** Дублирует plan.traffic_limit_bytes: у подписки лимит зафиксирован на момент покупки. */
  traffic_limit_bytes: number | null;
  traffic_period_start: string | null;
  device_limit: number;
  devices_used: number;
  auto_renew: boolean;
}

export type Platform = "ios" | "android" | "windows" | "macos" | "linux";

export interface Device {
  id: string;
  name: string;
  platform: Platform;
  issued_at: string;
  cert_expires_at: string;
  last_seen_at: string | null;
  is_online: boolean;
  /** Потрачено за текущий период подписки. */
  traffic_used_bytes: number;
}

export interface CreateDeviceInput {
  name: string;
  platform: Platform;
}

/**
 * Ответ на выпуск устройства. Пароль и ссылка приходят один раз и
 * не должны попадать ни в кэш, ни в хранилища браузера, ни в URL.
 */
export interface IssuedDevice {
  device: Device;
  p12_password: string;
  download_url: string;
  /** ISO 8601 UTC, обычно issued_at + 15 минут. */
  download_expires_at: string;
}

export interface Checkout {
  checkout_url: string;
  payment_id: string;
}

export interface ConnectionInfo {
  /** Хост шлюза: vpn.example.com */
  server_host: string;
  /** Полный адрес с камуфляж-токеном, его вводит клиент в AnyConnect. */
  gateway_url: string;
}
