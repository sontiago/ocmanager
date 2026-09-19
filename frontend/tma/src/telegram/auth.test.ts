import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  initDataRaw: vi.fn<() => string | undefined>(),
  initDataState: vi.fn<() => { user?: unknown } | undefined>(),
}));

vi.mock("@telegram-apps/sdk-react", () => ({
  initDataRaw: mocks.initDataRaw,
  initDataState: mocks.initDataState,
}));

const { getInitDataRaw, getTelegramUser, getTelegramLang } =
  await import("./auth");

describe("telegram/auth", () => {
  beforeEach(() => {
    mocks.initDataRaw.mockReset();
    mocks.initDataState.mockReset();
  });

  it("отдаёт сырую строку initData", () => {
    mocks.initDataRaw.mockReturnValue("user=%7B%7D&hash=abc");
    expect(getInitDataRaw()).toBe("user=%7B%7D&hash=abc");
  });

  it("не падает вне Telegram, а возвращает undefined", () => {
    mocks.initDataRaw.mockImplementation(() => {
      throw new Error("LaunchParamsRetrieveError");
    });
    expect(getInitDataRaw()).toBeUndefined();
  });

  it("отдаёт пользователя", () => {
    mocks.initDataState.mockReturnValue({
      user: { id: 1, first_name: "Иван", language_code: "ru" },
    });
    expect(getTelegramUser()?.first_name).toBe("Иван");
  });

  it("русский язык клиента распознаётся", () => {
    mocks.initDataState.mockReturnValue({
      user: { id: 1, language_code: "ru" },
    });
    expect(getTelegramLang()).toBe("ru");
  });

  it("неподдерживаемый язык клиента даёт en", () => {
    mocks.initDataState.mockReturnValue({
      user: { id: 1, language_code: "de" },
    });
    expect(getTelegramLang()).toBe("en");
  });

  it("отсутствие языка даёт ru — дефолт инсталляции", () => {
    mocks.initDataState.mockReturnValue({ user: { id: 1 } });
    expect(getTelegramLang()).toBe("ru");
  });
});
