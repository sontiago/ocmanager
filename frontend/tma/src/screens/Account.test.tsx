import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
});
