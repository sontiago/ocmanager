import type { ConnectionInfo, Me, Plan } from "../types";

const GB = 1024 ** 3;

export const TRIAL_PLAN: Plan = {
  code: "trial",
  name: "Пробный период",
  description: "3 дня и 5 ГБ, чтобы проверить скорость",
  duration_days: 3,
  device_limit: 1,
  traffic_limit_bytes: 5 * GB,
  speed_limit_kbps: null,
  price_amount: 0,
  currency: "RUB",
  is_trial: true,
  sort_order: 0,
};

// Цены и лимиты — демонстрационные (C7.1). Спецификация их не фиксирует:
// тарифы живут в таблице `plans`, в проде приходят с сервера. Числа здесь
// намеренно отличаются от прототипа — те так же произвольны. Правило одно:
// форма записи повторяет колонки `plans` один в один (C7.2), иначе Задача 20
// превратится в переписывание экранов вместо сверки типов.
export const PLANS: Plan[] = [
  {
    code: "month_1",
    name: "Месяц",
    description: "3 устройства, 200 ГБ трафика",
    duration_days: 30,
    device_limit: 3,
    traffic_limit_bytes: 200 * GB,
    speed_limit_kbps: null,
    price_amount: 29900,
    currency: "RUB",
    is_trial: false,
    sort_order: 10,
  },
  {
    code: "month_6",
    name: "Полгода",
    description: "5 устройств, безлимитный трафик",
    duration_days: 180,
    device_limit: 5,
    traffic_limit_bytes: null,
    speed_limit_kbps: null,
    price_amount: 149900,
    currency: "RUB",
    is_trial: false,
    sort_order: 20,
  },
  {
    code: "year_1",
    name: "Год",
    description: "5 устройств, безлимитный трафик, лучшая цена",
    duration_days: 365,
    device_limit: 5,
    traffic_limit_bytes: null,
    speed_limit_kbps: null,
    price_amount: 249900,
    currency: "RUB",
    is_trial: false,
    sort_order: 30,
  },
];

export const CONNECTION: ConnectionInfo = {
  server_host: "vpn.example.com",
  gateway_url: "https://vpn.example.com/f4a91c7b",
};

export const ME: Me = {
  telegram_id: 99281932,
  first_name: "Иван",
  username: "ivan",
  lang: "ru",
  is_blocked: false,
  trial_available: true,
};
