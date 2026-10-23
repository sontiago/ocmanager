import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { createMockClient } from "../api/mock/client";
import { resetStore, setLatency } from "../api/mock/store";
import { renderWithProviders } from "../test/renderWithProviders";
import { Account } from "./Account";

const links = vi.hoisted(() => ({
  openExternal: vi.fn(),
  openInTelegram: vi.fn(),
  closeApp: vi.fn(),
}));
vi.mock("../telegram/links", () => links);

/** В этом окружении localStorage нет ни у Node, ни у jsdom. */
function installMemoryStorage(): void {
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
      key: () => null,
      length: 0,
    } as Storage,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  installMemoryStorage();
  resetStore("active");
  setLatency(0);
  document.documentElement.removeAttribute("data-theme");
});

describe("экран аккаунта", () => {
  it("печатает Telegram ID без разрядных пробелов", async () => {
    renderWithProviders(<Account />);
    // 99 281 932 читалось бы как количество; это идентификатор.
    expect(await screen.findByText("99281932")).toBeVisible();
  });

  it("язык показан фактом: без шеврона и без нажатия", async () => {
    renderWithProviders(<Account />);
    const row = await screen.findByText("Язык");
    expect(row.closest("button")).toBeNull();
    expect(screen.getByText("Русский")).toBeVisible();
  });

  it("выбор темы переставляет data-theme и переживает перезапуск", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Тема/ }));

    const sheet = within(screen.getByRole("dialog"));
    await userEvent.click(sheet.getByRole("radio", { name: /Тёмная/ }));

    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("dark"),
    );
    expect(localStorage.getItem("ocm-theme")).toBe("dark");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("текущая тема отмечена в листе выбора", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Тема/ }));

    const sheet = within(screen.getByRole("dialog"));
    expect(
      sheet.getByRole("radio", { name: /Как в Telegram/ }),
    ).toHaveAttribute("aria-checked", "true");
    expect(sheet.getByRole("radio", { name: /Светлая/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("поддержка открывается внутри Telegram, а не в браузере", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Поддержка/ }),
    );
    expect(links.openInTelegram).toHaveBeenCalledWith(
      "https://t.me/ocmanager_help",
    );
    expect(links.openExternal).not.toHaveBeenCalled();
  });

  it("сбой запроса не ломает экран: тема остаётся переключаемой", async () => {
    const { setFault } = await import("../api/mock/store");
    setFault("network");
    renderWithProviders(<Account />);

    expect(await screen.findByRole("button", { name: /Тема/ })).toBeVisible();
    expect(screen.queryByText("Что-то пошло не так")).toBeNull();
    setFault("none");
  });

  it("«Друзья и бонусы» ведут на экран друзей", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Account />} />
        <Route path="/friends" element={<p>экран друзей</p>} />
      </Routes>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Друзья и бонусы/ }));
    expect(await screen.findByText("экран друзей")).toBeVisible();
  });

  it("промокод: пустое поле не отправляется", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Промокод/ }));
    const sheet = within(screen.getByRole("dialog"));
    expect(sheet.getByRole("button", { name: "Применить" })).toBeDisabled();
  });

  it("промокод: успех показывает награду", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Промокод/ }));
    const sheet = within(screen.getByRole("dialog"));
    await userEvent.type(sheet.getByLabelText("Код промокода"), "welcome7");
    await userEvent.click(sheet.getByRole("button", { name: "Применить" }));
    expect(await sheet.findByText("Готово: +7 дн. к подписке")).toBeVisible();
  });

  it("промокод на трафик показывает гигабайты", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Промокод/ }));
    const sheet = within(screen.getByRole("dialog"));
    await userEvent.type(sheet.getByLabelText("Код промокода"), "gb50");
    await userEvent.click(sheet.getByRole("button", { name: "Применить" }));
    expect(await sheet.findByText("Готово: +50 ГБ трафика")).toBeVisible();
  });

  it("промокод: неверный код — сообщение об ошибке, поле остаётся", async () => {
    renderWithProviders(<Account />);
    await userEvent.click(await screen.findByRole("button", { name: /Промокод/ }));
    const sheet = within(screen.getByRole("dialog"));
    await userEvent.type(sheet.getByLabelText("Код промокода"), "nosuch");
    await userEvent.click(sheet.getByRole("button", { name: "Применить" }));
    expect(
      await sheet.findByText("Промокод недействителен или закончился."),
    ).toBeVisible();
    expect(sheet.getByLabelText("Код промокода")).toHaveValue("nosuch");
  });

  it("промокод: повторный ввод — «уже использовали»", async () => {
    renderWithProviders(<Account />);
    for (let i = 0; i < 2; i++) {
      await userEvent.click(await screen.findByRole("button", { name: /Промокод/ }));
      const sheet = within(screen.getByRole("dialog"));
      await userEvent.clear(sheet.getByLabelText("Код промокода"));
      await userEvent.type(sheet.getByLabelText("Код промокода"), "welcome7");
      await userEvent.click(sheet.getByRole("button", { name: "Применить" }));
      if (i === 0) {
        await sheet.findByText(/Готово/);
        await userEvent.keyboard("{Escape}");
      }
    }
    expect(
      await within(screen.getByRole("dialog")).findByText("Вы уже использовали этот промокод."),
    ).toBeVisible();
  });

  it("значки реферальной программы показаны в аккаунте", async () => {
    const base = createMockClient();
    renderWithProviders(<Account />, {
      client: {
        ...base,
        getReferral: async () => ({
          ...(await base.getReferral()),
          badges: ["friend", "ambassador"],
        }),
      },
    });
    const row = await screen.findByText("Значки");
    expect(row).toBeVisible();
    expect(screen.getByText("Друг сети · Амбассадор")).toBeVisible();
  });

  it("без значков строки «Значки» нет", async () => {
    renderWithProviders(<Account />);
    await screen.findByText("99281932");
    expect(screen.queryByText("Значки")).toBeNull();
  });

  it("если реферальные данные не загрузились, аккаунт всё равно работает", async () => {
    const base = createMockClient();
    renderWithProviders(<Account />, {
      client: {
        ...base,
        getReferral: async () => {
          throw new ApiError("internal", 500);
        },
      },
    });
    expect(await screen.findByText("99281932")).toBeVisible();
    expect(screen.queryByText("Значки")).toBeNull();
  });
});
