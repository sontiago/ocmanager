import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/contract";
import { createMockClient } from "../api/mock/client";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { renderWithProviders } from "../test/renderWithProviders";
import { ErrorBoundary } from "./ErrorBoundary";
import { Gate } from "./Gate";
import userEvent from "@testing-library/user-event";

const getInitDataRaw = vi.hoisted(() => vi.fn<() => string | undefined>());
vi.mock("../telegram/auth", async () => {
  const actual =
    await vi.importActual<typeof import("../telegram/auth")>(
      "../telegram/auth",
    );
  return { ...actual, getInitDataRaw };
});

const links = vi.hoisted(() => ({
  openExternal: vi.fn(),
  openInTelegram: vi.fn(),
  closeApp: vi.fn(),
}));
vi.mock("../telegram/links", () => links);

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
  setFault("none");
  getInitDataRaw.mockReturnValue("user=%7B%7D&hash=a");
});

function show(client?: ApiClient) {
  return renderWithProviders(
    <Gate>
      <p>содержимое</p>
    </Gate>,
    { client: client ?? createMockClient() },
  );
}

describe("Gate", () => {
  it("работоспособное состояние пропускает дальше", async () => {
    show();
    await waitFor(() => expect(screen.getByText("содержимое")).toBeVisible());
  });

  it("без initData объясняет, что делать, и не трогает API", async () => {
    getInitDataRaw.mockReturnValue(undefined);
    const getMe = vi.fn();
    show({ ...createMockClient(), getMe });

    await waitFor(() =>
      expect(screen.getByText("Откройте приложение из Telegram")).toBeVisible(),
    );
    expect(screen.queryByText("содержимое")).toBeNull();
    // Запрос с заведомым 401 не отправляется вовсе.
    expect(getMe).not.toHaveBeenCalled();
  });

  it("заблокированному клиенту объясняет и даёт выход в поддержку", async () => {
    resetStore("blocked");
    show();

    await waitFor(() =>
      expect(screen.getByText("Доступ приостановлен")).toBeVisible(),
    );
    expect(screen.queryByText("содержимое")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: "Написать в поддержку" }),
    );
    expect(links.openInTelegram).toHaveBeenCalledWith(
      "https://t.me/ocmanager_help",
    );
  });

  it("сбой запроса даёт экран ошибки с повтором, а не белый экран", async () => {
    setFault("node_unavailable");
    show();

    await waitFor(() =>
      expect(
        screen.getByText("Сервер временно недоступен. Попробуйте позже."),
      ).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});

describe("граница ошибок", () => {
  function Boom(): never {
    throw new Error("рендер упал");
  }

  it("перехватывает исключение рендера и предлагает перезапуск", () => {
    // React печатает пойманную ошибку в консоль — глушим ради читаемого вывода.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderWithProviders(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Приложение не смогло продолжить")).toBeVisible();
    expect(screen.getByRole("button", { name: "Перезапустить" })).toBeVisible();
    spy.mockRestore();
  });
});
