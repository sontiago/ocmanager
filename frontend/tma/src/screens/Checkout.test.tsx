import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { PATHS, ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Checkout } from "./Checkout";

const links = vi.hoisted(() => ({
  openExternal: vi.fn(),
  closeApp: vi.fn(),
  openInTelegram: vi.fn(),
}));
vi.mock("../telegram/links", () => links);

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useNavigate: () => navigate };
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetStore("trial_used");
  setLatency(0);
  setFault("none");
});

/** Экран читает :planCode из адреса, поэтому монтируется настоящим маршрутом. */
function show(planCode: string) {
  return renderWithProviders(
    <Routes>
      <Route path={PATHS.checkout} element={<Checkout />} />
    </Routes>,
    { route: ROUTES.checkout(planCode) },
  );
}

describe("экран оплаты", () => {
  it("показывает скелет, пока каталог не пришёл", () => {
    setLatency(50);
    const { container } = show("month_1");
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("сводка называет сумму, тариф, период и способ оплаты", async () => {
    show("month_1");
    await waitFor(() => expect(screen.getByText(/299/)).toBeVisible());
    expect(screen.getByText("Месяц")).toBeVisible();
    expect(screen.getByText("30 дней")).toBeVisible();
    expect(screen.getByText("Tribute")).toBeVisible();
  });

  it("оплата открывает страницу провайдера и только потом закрывает приложение", async () => {
    show("month_1");
    await userEvent.click(
      await screen.findByRole("button", { name: "Перейти к оплате" }),
    );

    await waitFor(() => expect(links.openExternal).toHaveBeenCalledOnce());
    expect(links.openExternal.mock.calls[0][0]).toContain(
      "tribute.tg/checkout/month_1",
    );
    expect(links.closeApp).toHaveBeenCalledOnce();
    // Порядок — суть экрана: закрытое приложение уже ничего не откроет.
    expect(links.openExternal.mock.invocationCallOrder[0]).toBeLessThan(
      links.closeApp.mock.invocationCallOrder[0],
    );
  });

  it("сбой оплаты называет причину и никуда не уводит", async () => {
    show("month_1");
    const pay = await screen.findByRole("button", { name: "Перейти к оплате" });
    setFault("rate_limited");
    await userEvent.click(pay);

    await waitFor(() =>
      expect(
        screen.getByText("Слишком много запросов. Подождите минуту."),
      ).toBeVisible(),
    );
    expect(links.openExternal).not.toHaveBeenCalled();
    expect(links.closeApp).not.toHaveBeenCalled();
  });

  it("неизвестный тариф — не тупик, а выход в каталог", async () => {
    show("no_such_plan");
    await waitFor(() =>
      expect(screen.getByText("Тариф не найден")).toBeVisible(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать тариф" }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.plans);
  });

  it("сбой каталога даёт экран ошибки с повтором", async () => {
    setFault("network");
    show("month_1");
    await waitFor(() =>
      expect(screen.getByText("Что-то пошло не так")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
