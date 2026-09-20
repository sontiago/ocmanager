import { describe, expect, it } from "vitest";
import type { Plan, Subscription, SubscriptionStatus } from "../api/types";
import {
  canIssueDevice,
  daysLeft,
  isLive,
  statusMessageKey,
  trafficPercent,
} from "./subscription";

const GB = 1024 ** 3;
const DAY = 86_400_000;
const NOW = Date.UTC(2026, 4, 1, 12, 0, 0);

const plan: Plan = {
  code: "month_1",
  name: "Месяц",
  description: "",
  duration_days: 30,
  device_limit: 3,
  traffic_limit_bytes: 200 * GB,
  speed_limit_kbps: null,
  price_amount: 29900,
  currency: "RUB",
  is_trial: false,
  sort_order: 10,
};

function sub(over: Partial<Subscription> = {}): Subscription {
  return {
    id: "sub_1",
    plan,
    status: "active",
    started_at: new Date(NOW - 10 * DAY).toISOString(),
    expires_at: new Date(NOW + 20 * DAY).toISOString(),
    traffic_used_bytes: 50 * GB,
    traffic_limit_bytes: 200 * GB,
    traffic_period_start: new Date(NOW - 10 * DAY).toISOString(),
    device_limit: 3,
    devices_used: 1,
    auto_renew: true,
    ...over,
  };
}

describe("isLive", () => {
  it("active, trial и cancelled дают доступ", () => {
    for (const status of [
      "active",
      "trial",
      "cancelled",
    ] as SubscriptionStatus[]) {
      expect(isLive(sub({ status })), status).toBe(true);
    }
  });

  it("expired, exhausted, blocked и pending_payment доступа не дают", () => {
    for (const status of [
      "expired",
      "exhausted",
      "blocked",
      "pending_payment",
    ] as SubscriptionStatus[]) {
      expect(isLive(sub({ status })), status).toBe(false);
    }
  });

  it("отсутствие подписки — не доступ", () => {
    expect(isLive(null)).toBe(false);
  });
});

describe("daysLeft", () => {
  it("считает полные дни до окончания", () => {
    expect(daysLeft(sub(), NOW)).toBe(20);
  });

  it("округляет вверх: неполный день ещё оплачен", () => {
    expect(
      daysLeft(
        sub({ expires_at: new Date(NOW + 1.2 * DAY).toISOString() }),
        NOW,
      ),
    ).toBe(2);
  });

  it("прошедшая дата даёт ноль, а не отрицательное число", () => {
    expect(
      daysLeft(sub({ expires_at: new Date(NOW - 5 * DAY).toISOString() }), NOW),
    ).toBe(0);
  });

  it("бессрочная подписка даёт Infinity", () => {
    expect(daysLeft(sub({ expires_at: null }), NOW)).toBe(Infinity);
  });
});

describe("trafficPercent", () => {
  it("25 % от лимита", () => {
    expect(trafficPercent(sub())).toBe(25);
  });

  it("безлимит даёт null, а не 0", () => {
    expect(trafficPercent(sub({ traffic_limit_bytes: null }))).toBeNull();
  });

  it("перерасход не выходит за 100", () => {
    expect(trafficPercent(sub({ traffic_used_bytes: 500 * GB }))).toBe(100);
  });
});

describe("canIssueDevice", () => {
  it("можно, пока есть свободные слоты и доступ живой", () => {
    expect(canIssueDevice(sub({ devices_used: 2 }))).toBe(true);
  });

  it("нельзя при выбранном лимите", () => {
    expect(canIssueDevice(sub({ devices_used: 3 }))).toBe(false);
  });

  it("нельзя на истёкшей подписке", () => {
    expect(canIssueDevice(sub({ status: "expired", devices_used: 0 }))).toBe(
      false,
    );
  });

  it("можно при cancelled — период оплачен", () => {
    expect(canIssueDevice(sub({ status: "cancelled", devices_used: 0 }))).toBe(
      true,
    );
  });
});

describe("statusMessageKey", () => {
  it("каждому статусу соответствует ключ каталога", () => {
    expect(statusMessageKey(sub({ status: "cancelled" }))).toBe(
      "status.cancelled",
    );
    expect(statusMessageKey(sub({ status: "exhausted" }))).toBe(
      "status.exhausted",
    );
  });
});
