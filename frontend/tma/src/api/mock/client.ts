import type { ApiClient } from "../contract";
import { ApiError, type ApiErrorCode } from "../errors";
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
  SubscriptionStatus,
} from "../types";
import { getState, type FaultId } from "./store";

const DAY = 86_400_000;
const LINK_TTL_MS = 15 * 60_000;

/** Статусы, при которых клиент имеет право пользоваться сервисом. */
const LIVE_STATUSES: ReadonlySet<SubscriptionStatus> = new Set([
  "trial",
  "active",
  "cancelled",
]);

const FAULT_TO_ERROR: Record<
  Exclude<FaultId, "none">,
  [ApiErrorCode, number]
> = {
  network: ["network", 0],
  internal: ["internal", 500],
  rate_limited: ["rate_limited", 429],
  node_unavailable: ["node_unavailable", 503],
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Каждая операция проходит через это: задержка + сконфигурированный сбой. */
async function transport(): Promise<void> {
  const { latencyMs, fault } = getState();
  if (latencyMs > 0) await sleep(latencyMs);
  if (fault !== "none") {
    const [code, status] = FAULT_TO_ERROR[fault];
    throw new ApiError(code, status);
  }
}

/** Наружу отдаются копии: экраны не должны иметь возможности править стор. */
function copy<T>(value: T): T {
  return structuredClone(value);
}

function randomPassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  return Array.from(
    { length: 12 },
    () => alphabet[Math.floor(Math.random() * alphabet.length)],
  ).join("");
}

function requireLiveSubscription(): Subscription {
  const state = getState();
  if (state.me.is_blocked) {
    throw new ApiError("subscription_inactive", 403);
  }
  const sub = state.subscription;
  if (!sub || !LIVE_STATUSES.has(sub.status)) {
    throw new ApiError("subscription_inactive", 409);
  }
  return sub;
}

export function createMockClient(): ApiClient {
  return {
    async getMe(): Promise<Me> {
      await transport();
      return copy(getState().me);
    },

    async listPlans(): Promise<Plan[]> {
      await transport();
      // Trial-тариф скрытый: он есть в сторе, но в каталог не попадает.
      return copy(getState().plans).sort((a, b) => a.sort_order - b.sort_order);
    },

    async getSubscription(): Promise<Subscription | null> {
      await transport();
      return copy(getState().subscription);
    },

    async startTrial(): Promise<Subscription> {
      await transport();
      const state = getState();
      if (!state.me.trial_available) {
        throw new ApiError("trial_already_used", 409);
      }

      const plan = state.trialPlan;
      const now = Date.now();
      const sub: Subscription = {
        id: `sub_trial_${now}`,
        plan: copy(plan),
        status: "trial",
        started_at: new Date(now).toISOString(),
        expires_at: new Date(now + plan.duration_days * DAY).toISOString(),
        traffic_used_bytes: 0,
        traffic_limit_bytes: plan.traffic_limit_bytes,
        traffic_period_start: new Date(now).toISOString(),
        device_limit: plan.device_limit,
        devices_used: 0,
        auto_renew: false,
      };

      state.subscription = sub;
      state.me.trial_available = false;
      return copy(sub);
    },

    async createCheckout(planCode: string): Promise<Checkout> {
      await transport();
      const state = getState();
      const plan = state.plans.find((p) => p.code === planCode);
      if (!plan) throw new ApiError("not_found", 404, `нет тарифа ${planCode}`);

      const paymentId = `pay_${Date.now().toString(36)}`;
      return {
        payment_id: paymentId,
        checkout_url: `https://web.tribute.tg/checkout/${plan.code}?payload=${paymentId}`,
      };
    },

    async listDevices(): Promise<Device[]> {
      await transport();
      return copy(getState().devices);
    },

    async createDevice(input: CreateDeviceInput): Promise<IssuedDevice> {
      await transport();
      const state = getState();
      const sub = requireLiveSubscription();

      if (state.devices.length >= sub.device_limit) {
        throw new ApiError("device_limit_reached", 409);
      }

      const name = input.name.trim();
      if (!name) throw new ApiError("internal", 422, "пустое имя устройства");

      state.deviceSeq += 1;
      const now = Date.now();
      const device: Device = {
        id: `dev_${state.deviceSeq}_${now.toString(36)}`,
        name,
        platform: input.platform,
        issued_at: new Date(now).toISOString(),
        // Срок сертификата — 397 дней, он развязан со сроком подписки.
        cert_expires_at: new Date(now + 397 * DAY).toISOString(),
        last_seen_at: null,
        is_online: false,
        traffic_used_bytes: 0,
      };

      state.devices.push(device);
      sub.devices_used = state.devices.length;

      return {
        device: copy(device),
        p12_password: randomPassword(),
        download_url: `https://app.example.com/download/${crypto.randomUUID()}`,
        download_expires_at: new Date(now + LINK_TTL_MS).toISOString(),
      };
    },

    async revokeDevice(deviceId: string): Promise<void> {
      await transport();
      const state = getState();
      const index = state.devices.findIndex((d) => d.id === deviceId);
      if (index === -1) throw new ApiError("not_found", 404);

      state.devices.splice(index, 1);
      if (state.subscription) {
        state.subscription.devices_used = state.devices.length;
      }
    },

    async getConnection(): Promise<ConnectionInfo> {
      await transport();
      return copy(getState().connection);
    },
  };
}
