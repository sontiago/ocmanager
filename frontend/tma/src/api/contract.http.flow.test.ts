import { describe, expect, it } from "vitest";
import { ApiError } from "./errors";
import { createHttpClient } from "./http";

const BASE_URL = process.env.TMA_E2E_BASE_URL;

/** Новый клиент на каждый прогон: пробный период выдаётся один раз. Подпись поддельная. */
function freshInitData(): string {
  const user = {
    id: 8_000_000_000 + Math.floor(Math.random() * 1_000_000),
    first_name: "E2E",
    language_code: "ru",
  };
  return new URLSearchParams([
    ["user", JSON.stringify(user)],
    ["auth_date", Math.floor(Date.now() / 1000).toString()],
    ["hash", "dev-mock-hash"],
  ]).toString();
}

// Нужен бэкенд с OCM_TMA_ALLOW_DEV_INITDATA=true, созданным CA и тарифом trial (миграция).
const suite = BASE_URL ? describe : describe.skip;

suite("HTTP-клиент: путь клиента от первого запроса до отзыва устройства", () => {
  it("trial → устройство → .p12 один раз → отзыв", async () => {
    const raw = freshInitData();
    const api = createHttpClient({ baseUrl: BASE_URL ?? "", getInitDataRaw: () => raw });

    const me = await api.getMe();
    expect(me.trial_available).toBe(true);
    expect(await api.getSubscription()).toBeNull();

    const sub = await api.startTrial();
    expect(sub.status).toBe("trial");
    await expect(api.startTrial()).rejects.toMatchObject({ code: "trial_already_used" });

    const issued = await api.createDevice({ name: "e2e", platform: "linux" });
    expect(issued.p12_password.length).toBeGreaterThan(8);
    const first = await fetch(issued.download_url);
    expect(first.status).toBe(200);
    expect((await first.arrayBuffer()).byteLength).toBeGreaterThan(500);
    expect((await fetch(issued.download_url)).status).toBe(404);

    await expect(
      api.createDevice({ name: "second", platform: "ios" }),
    ).rejects.toMatchObject({ code: "device_limit_reached" });

    const devices = await api.listDevices();
    expect(devices.map((d) => d.id)).toEqual([issued.device.id]);
    expect((await api.getSubscription())?.devices_used).toBe(1);

    await api.revokeDevice(issued.device.id);
    expect(await api.listDevices()).toEqual([]);
    await expect(api.revokeDevice(issued.device.id)).resolves.toBeUndefined();
    await expect(api.revokeDevice("999999999")).rejects.toBeInstanceOf(ApiError);
  });

  it("чужая подпись — unauthorized, а не internal", async () => {
    const api = createHttpClient({
      baseUrl: BASE_URL ?? "",
      getInitDataRaw: () => "user=%7B%7D&auth_date=1&hash=00",
    });
    await expect(api.getMe()).rejects.toMatchObject({ code: "unauthorized" });
  });
});
