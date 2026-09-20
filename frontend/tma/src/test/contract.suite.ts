import { describe, expect, it } from "vitest";
import type { ApiClient } from "../api/contract";

/**
 * Набор инвариантов контракта, не зависящих от реализации.
 * Запускается против мока сейчас и против HTTP-клиента в Задаче 20.
 */
export function runContractSuite(
  name: string,
  makeClient: () => Promise<ApiClient>,
): void {
  describe(`контракт ApiClient: ${name}`, () => {
    it("listPlans отдаёт массив, отсортированный по sort_order", async () => {
      const plans = await (await makeClient()).listPlans();
      expect(Array.isArray(plans)).toBe(true);
      const orders = plans.map((p) => p.sort_order);
      expect(orders).toEqual([...orders].sort((a, b) => a - b));
    });

    it("в каталоге нет trial-тарифа — он скрытый", async () => {
      const plans = await (await makeClient()).listPlans();
      expect(plans.some((p) => p.is_trial)).toBe(false);
    });

    it("цены — целые неотрицательные числа", async () => {
      const plans = await (await makeClient()).listPlans();
      for (const p of plans) {
        expect(Number.isInteger(p.price_amount)).toBe(true);
        expect(p.price_amount).toBeGreaterThanOrEqual(0);
      }
    });

    it("даты подписки — валидный ISO 8601", async () => {
      const sub = await (await makeClient()).getSubscription();
      if (!sub) return;
      for (const value of [sub.started_at, sub.expires_at]) {
        if (value === null) continue;
        expect(Number.isNaN(Date.parse(value))).toBe(false);
      }
    });

    it("devices_used подписки совпадает с длиной списка устройств", async () => {
      const api = await makeClient();
      const [sub, devices] = await Promise.all([
        api.getSubscription(),
        api.listDevices(),
      ]);
      if (!sub) return;
      expect(sub.devices_used).toBe(devices.length);
    });

    it("устройств не больше лимита тарифа", async () => {
      const api = await makeClient();
      const [sub, devices] = await Promise.all([
        api.getSubscription(),
        api.listDevices(),
      ]);
      if (!sub) return;
      expect(devices.length).toBeLessThanOrEqual(sub.device_limit);
    });

    it("gateway_url содержит server_host", async () => {
      const conn = await (await makeClient()).getConnection();
      expect(conn.gateway_url).toContain(conn.server_host);
    });
  });
}
