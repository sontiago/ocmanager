import type { Device, Plan, Subscription } from "../types";
import { PLANS, TRIAL_PLAN } from "./fixtures";

export type ScenarioId =
  | "new_user"
  | "trial_used"
  | "trial_active"
  | "active"
  | "expiring_soon"
  | "traffic_low"
  | "exhausted"
  | "expired"
  | "cancelled"
  | "blocked"
  | "device_limit";

export const SCENARIOS: readonly { id: ScenarioId; label: string }[] = [
  { id: "new_user", label: "Новый клиент, trial доступен" },
  { id: "trial_used", label: "Без подписки, trial израсходован" },
  { id: "trial_active", label: "Активный пробный период" },
  { id: "active", label: "Платная подписка, 2 из 3 устройств" },
  { id: "expiring_soon", label: "Истекает через 2 дня" },
  { id: "traffic_low", label: "Осталось 12 % трафика" },
  { id: "exhausted", label: "Трафик исчерпан" },
  { id: "expired", label: "Подписка истекла" },
  { id: "cancelled", label: "Автопродление выключено, доступ есть" },
  { id: "blocked", label: "Клиент заблокирован" },
  { id: "device_limit", label: "Лимит устройств выбран полностью" },
];

const GB = 1024 ** 3;
const DAY = 86_400_000;

const iso = (offsetMs: number): string =>
  new Date(Date.now() + offsetMs).toISOString();

function device(
  over: Partial<Device> & Pick<Device, "id" | "name" | "platform">,
): Device {
  return {
    issued_at: iso(-20 * DAY),
    cert_expires_at: iso(377 * DAY),
    last_seen_at: iso(-2 * 3600_000),
    is_online: false,
    traffic_used_bytes: 12 * GB,
    ...over,
  };
}

function subscription(plan: Plan, over: Partial<Subscription>): Subscription {
  return {
    id: "sub_1",
    plan,
    status: "active",
    started_at: iso(-10 * DAY),
    expires_at: iso(20 * DAY),
    traffic_used_bytes: 34 * GB,
    traffic_limit_bytes: plan.traffic_limit_bytes,
    traffic_period_start: iso(-10 * DAY),
    device_limit: plan.device_limit,
    devices_used: 2,
    auto_renew: true,
    ...over,
  };
}

export interface ScenarioState {
  subscription: Subscription | null;
  devices: Device[];
  trialAvailable: boolean;
  isBlocked: boolean;
}

const MONTH = PLANS[0];

const iphone = device({
  id: "dev_1",
  name: "iPhone Ивана",
  platform: "ios",
  is_online: true,
});
const laptop = device({
  id: "dev_2",
  name: "MacBook",
  platform: "macos",
  traffic_used_bytes: 22 * GB,
});
const desktop = device({
  id: "dev_3",
  name: "Домашний ПК",
  platform: "windows",
  last_seen_at: null,
  traffic_used_bytes: 0,
});

export function buildScenario(id: ScenarioId): ScenarioState {
  switch (id) {
    case "new_user":
      return {
        subscription: null,
        devices: [],
        trialAvailable: true,
        isBlocked: false,
      };

    case "trial_used":
      return {
        subscription: null,
        devices: [],
        trialAvailable: false,
        isBlocked: false,
      };

    case "trial_active":
      return {
        subscription: subscription(TRIAL_PLAN, {
          status: "trial",
          expires_at: iso(2 * DAY),
          started_at: iso(-1 * DAY),
          traffic_used_bytes: Math.round(1.4 * GB),
          traffic_limit_bytes: TRIAL_PLAN.traffic_limit_bytes,
          device_limit: 1,
          devices_used: 1,
          auto_renew: false,
        }),
        devices: [iphone],
        trialAvailable: false,
        isBlocked: false,
      };

    case "active":
      return {
        subscription: subscription(MONTH, {}),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      };

    case "expiring_soon":
      return {
        subscription: subscription(MONTH, { expires_at: iso(2 * DAY) }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      };

    case "traffic_low":
      return {
        subscription: subscription(MONTH, { traffic_used_bytes: 176 * GB }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      };

    case "exhausted":
      return {
        subscription: subscription(MONTH, {
          status: "exhausted",
          traffic_used_bytes: 200 * GB,
        }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      };

    case "expired":
      return {
        subscription: subscription(MONTH, {
          status: "expired",
          started_at: iso(-40 * DAY),
          expires_at: iso(-3 * DAY),
        }),
        devices: [],
        trialAvailable: false,
        isBlocked: false,
      };

    case "cancelled":
      return {
        subscription: subscription(MONTH, {
          status: "cancelled",
          auto_renew: false,
        }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      };

    case "blocked":
      return {
        subscription: subscription(MONTH, { status: "blocked" }),
        devices: [iphone],
        trialAvailable: false,
        isBlocked: true,
      };

    case "device_limit":
      return {
        subscription: subscription(MONTH, { devices_used: 3 }),
        devices: [iphone, laptop, desktop],
        trialAvailable: false,
        isBlocked: false,
      };
  }
}

export const DEFAULT_SCENARIO: ScenarioId = "active";
