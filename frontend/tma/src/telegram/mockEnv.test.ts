import { beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  emitEvent: vi.fn(),
  mockTelegramEnv: vi.fn(),
  retrieveRawLaunchParams: vi.fn(),
}));
vi.mock("@telegram-apps/sdk-react", () => sdk);

async function load() {
  vi.resetModules();
  return import("./mockEnv");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  vi.spyOn(console, "info").mockImplementation(() => undefined);
});

describe("mockEnv", () => {
  it("без параметров запуска (обычный браузер) окружение мокается", async () => {
    sdk.retrieveRawLaunchParams.mockImplementation(() => {
      throw new Error("нет параметров");
    });
    await load();
    expect(sdk.mockTelegramEnv).toHaveBeenCalledOnce();
  });

  it("поверх собственной подделки мок включается снова (перезагрузка в браузере)", async () => {
    sdk.retrieveRawLaunchParams.mockReturnValue(
      "tgWebAppData=user%3D1%26hash%3Ddev-mock-hash&tgWebAppVersion=8.0",
    );
    await load();
    expect(sdk.mockTelegramEnv).toHaveBeenCalledOnce();
  });

  it("поверх настоящих параметров Telegram мок не включается: иначе перезагрузка даёт 401", async () => {
    sdk.retrieveRawLaunchParams.mockReturnValue(
      "tgWebAppData=user%3D1%26hash%3D0a1b2c&tgWebAppVersion=8.0",
    );
    await load();
    expect(sdk.mockTelegramEnv).not.toHaveBeenCalled();
  });
});
