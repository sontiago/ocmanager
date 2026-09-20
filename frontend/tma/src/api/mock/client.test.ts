import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "../errors";
import { createMockClient } from "./client";
import { getState, resetStore, setFault, setLatency } from "./store";

const api = createMockClient();

beforeEach(() => {
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
  setFault("none");
});

describe("mock/client — чтение", () => {
  it("отдаёт активные тарифы без скрытого trial-тарифа", async () => {
    const plans = await api.listPlans();
    expect(plans.map((p) => p.code)).toEqual(["month_1", "month_6", "year_1"]);
  });

  it("отдаёт подписку сценария", async () => {
    expect((await api.getSubscription())?.status).toBe("active");
  });

  it("для нового клиента подписки нет", async () => {
    resetStore("new_user");
    expect(await api.getSubscription()).toBeNull();
  });
});

describe("mock/client — trial", () => {
  it("создаёт подписку на trial-тарифе и закрывает повторную попытку", async () => {
    resetStore("new_user");
    const sub = await api.startTrial();
    expect(sub.status).toBe("trial");
    expect(sub.plan.is_trial).toBe(true);
    expect((await api.getMe()).trial_available).toBe(false);

    await expect(api.startTrial()).rejects.toMatchObject({
      code: "trial_already_used",
    });
  });

  it("trial недоступен, если он уже был израсходован", async () => {
    resetStore("trial_used");
    await expect(api.startTrial()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("mock/client — устройства", () => {
  it("выпускает устройство, кладёт его в список и отдаёт пароль один раз", async () => {
    const before = (await api.listDevices()).length;
    const issued = await api.createDevice({
      name: "Планшет",
      platform: "android",
    });

    expect(issued.p12_password).toMatch(/^[A-Za-z0-9]{12}$/);
    expect(issued.download_url).toContain("/download/");
    expect(new Date(issued.download_expires_at).getTime()).toBeGreaterThan(
      Date.now(),
    );
    expect(await api.listDevices()).toHaveLength(before + 1);
    expect((await api.getSubscription())?.devices_used).toBe(before + 1);
  });

  it("отказывает при исчерпанном лимите устройств", async () => {
    resetStore("device_limit");
    await expect(
      api.createDevice({ name: "Ещё один", platform: "ios" }),
    ).rejects.toMatchObject({ code: "device_limit_reached", status: 409 });
  });

  it("отказывает в выпуске на истёкшей подписке", async () => {
    resetStore("expired");
    await expect(
      api.createDevice({ name: "X", platform: "ios" }),
    ).rejects.toMatchObject({ code: "subscription_inactive" });
  });

  it("разрешает выпуск при cancelled — доступ живёт до expires_at", async () => {
    resetStore("cancelled");
    await expect(
      api.createDevice({ name: "X", platform: "ios" }),
    ).resolves.toBeTruthy();
  });

  it("отзыв убирает устройство из списка", async () => {
    const [first] = await api.listDevices();
    await api.revokeDevice(first.id);
    const rest = await api.listDevices();
    expect(rest.find((d) => d.id === first.id)).toBeUndefined();
    expect((await api.getSubscription())?.devices_used).toBe(rest.length);
  });

  it("отзыв несуществующего устройства даёт not_found", async () => {
    await expect(api.revokeDevice("dev_нет")).rejects.toMatchObject({
      code: "not_found",
      status: 404,
    });
  });
});

describe("mock/client — покупка", () => {
  it("отдаёт checkout-ссылку по коду тарифа", async () => {
    const checkout = await api.createCheckout("month_1");
    expect(checkout.checkout_url).toMatch(/^https:\/\//);
    expect(checkout.payment_id).toBeTruthy();
  });

  it("неизвестный тариф даёт not_found", async () => {
    await expect(api.createCheckout("нет-такого")).rejects.toMatchObject({
      code: "not_found",
    });
  });
});

describe("mock/client — инъекция сбоев", () => {
  it("fault=network даёт повторяемую ошибку сети", async () => {
    setFault("network");
    const err = await api.listPlans().catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network");
    expect((err as ApiError).retryable).toBe(true);
  });

  it("fault=rate_limited даёт 429 и не повторяется", async () => {
    setFault("rate_limited");
    const err = await api.listDevices().catch((e: ApiError) => e);
    expect((err as ApiError).status).toBe(429);
    expect((err as ApiError).retryable).toBe(false);
  });

  it("заблокированный клиент получает отказ на изменяющих операциях", async () => {
    resetStore("blocked");
    await expect(
      api.createDevice({ name: "X", platform: "ios" }),
    ).rejects.toMatchObject({ code: "subscription_inactive" });
  });

  it("латентность соблюдается", async () => {
    setLatency(60);
    const started = Date.now();
    await api.listPlans();
    expect(Date.now() - started).toBeGreaterThanOrEqual(50);
  });
});

describe("mock/client — соединение", () => {
  it("отдаёт хост шлюза и адрес с камуфляж-токеном", async () => {
    const conn = await api.getConnection();
    expect(conn.server_host).toBe("vpn.example.com");
    expect(conn.gateway_url).toContain(conn.server_host);
  });

  it("состояние стора не утекает наружу по ссылке", async () => {
    const devices = await api.listDevices();
    devices[0].name = "подменено";
    expect(getState().devices[0].name).not.toBe("подменено");
  });
});
