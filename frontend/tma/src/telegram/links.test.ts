import { beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  openLink: vi.fn(),
  openTelegramLink: vi.fn(),
  close: vi.fn(),
  // Доступность методов — главный предмет этих тестов: вне Telegram
  // isAvailable() возвращает false, и модуль обязан это пережить.
  available: { link: true, tgLink: true, close: true },
}));

vi.mock("@telegram-apps/sdk-react", () => ({
  openLink: Object.assign(sdk.openLink, {
    isAvailable: () => sdk.available.link,
  }),
  openTelegramLink: Object.assign(sdk.openTelegramLink, {
    isAvailable: () => sdk.available.tgLink,
  }),
  miniApp: {
    close: Object.assign(sdk.close, { isAvailable: () => sdk.available.close }),
  },
}));

const { closeApp, openExternal, openInTelegram } = await import("./links");

beforeEach(() => {
  vi.clearAllMocks();
  sdk.available = { link: true, tgLink: true, close: true };
});

describe("openExternal", () => {
  it("внутри Telegram открывает ссылку средствами клиента", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    openExternal("https://pay.example/checkout");

    expect(sdk.openLink).toHaveBeenCalledWith("https://pay.example/checkout", {
      tryInstantView: false,
    });
    expect(open).not.toHaveBeenCalled();
  });

  it("вне Telegram открывает вкладку и рвёт связь с opener", () => {
    sdk.available.link = false;
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    openExternal("https://pay.example/checkout");

    expect(open).toHaveBeenCalledWith(
      "https://pay.example/checkout",
      "_blank",
      "noopener,noreferrer",
    );
  });
});

describe("openInTelegram", () => {
  it("ссылку t.me отдаёт клиенту, а не браузеру", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    openInTelegram("https://t.me/ocmanager_bot");

    expect(sdk.openTelegramLink).toHaveBeenCalledWith(
      "https://t.me/ocmanager_bot",
    );
    expect(open).not.toHaveBeenCalled();
  });
});

describe("closeApp", () => {
  it("закрывает мини-приложение", () => {
    closeApp();
    expect(sdk.close).toHaveBeenCalledOnce();
  });

  it("в браузере ничего не делает и не бросает", () => {
    sdk.available.close = false;
    expect(() => closeApp()).not.toThrow();
    expect(sdk.close).not.toHaveBeenCalled();
  });
});
