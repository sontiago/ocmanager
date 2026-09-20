import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors";
import { createHttpClient } from "./http";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const RAW = "user=%7B%7D&hash=a";

/** Явная передача initData — в том числе отсутствующей. */
function makeWithRaw(fetchImpl: typeof fetch, raw: string | undefined) {
  return createHttpClient({
    baseUrl: "/api",
    getInitDataRaw: () => raw,
    fetchImpl,
  });
}

function make(fetchImpl: typeof fetch) {
  return makeWithRaw(fetchImpl, RAW);
}

describe("http client", () => {
  it("кладёт initData в заголовок Authorization по схеме tma", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json([]));
    await make(fetchImpl).listPlans();

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/tma/plans");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "tma user=%7B%7D&hash=a",
    );
  });

  it("без initData не ходит в сеть, а сразу даёт unauthorized", async () => {
    const fetchImpl = vi.fn();
    await expect(
      makeWithRaw(fetchImpl, undefined).listPlans(),
    ).rejects.toMatchObject({
      code: "unauthorized",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("разворачивает конверт подписки", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ subscription: null }));
    expect(await make(fetchImpl).getSubscription()).toBeNull();
  });

  it("маппит код ошибки из тела ответа", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        json(
          { error: { code: "device_limit_reached", message: "лимит" } },
          409,
        ),
      );
    const err = await make(fetchImpl)
      .createDevice({ name: "X", platform: "ios" })
      .catch((e: ApiError) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("device_limit_reached");
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe("лимит");
  });

  it("неизвестный код ошибки не роняет клиент, а становится internal", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json({ error: { code: "квантовый_сбой" } }, 500));
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: "internal",
    });
  });

  it("ответ без JSON-тела не роняет клиент", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response("<html>502</html>", { status: 502 }));
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: "internal",
      status: 502,
    });
  });

  it("401 с истёкшей initData отличается от обычного 401", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json({ error: { code: "initdata_expired" } }, 401));
    await expect(make(fetchImpl).getMe()).rejects.toMatchObject({
      code: "initdata_expired",
    });
  });

  it("обрыв соединения превращается в network", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: "network",
      status: 0,
    });
  });

  it("204 на отзыве устройства не пытается парсить тело", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    await expect(
      make(fetchImpl).revokeDevice("dev_1"),
    ).resolves.toBeUndefined();
  });

  it("id устройства экранируется в пути", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    await make(fetchImpl).revokeDevice("dev/../admin");
    expect((fetchImpl.mock.calls[0] as [string])[0]).toBe(
      "/api/tma/devices/dev%2F..%2Fadmin",
    );
  });

  it("POST отправляет тело в JSON", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json({ device: {}, p12_password: "x" }));
    await make(fetchImpl).createDevice({
      name: "Планшет",
      platform: "android",
    });
    const init = (fetchImpl.mock.calls[0] as [string, RequestInit])[1];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"name":"Планшет","platform":"android"}');
  });
});
