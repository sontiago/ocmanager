import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router";
import { ApiError } from "../api/errors";
import { createMockClient } from "../api/mock/client";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { PATHS, ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Checkout } from "./Checkout";

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

  it("ссылка на оплату создаётся сама, а кнопка — настоящая ссылка", async () => {
    show("month_1");

    const link = await screen.findByRole("link", { name: "Перейти к оплате" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("tribute.tg/checkout/month_1"),
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // Нажимать ничего не пришлось: приложение не закрывается и не уводит само.
    expect(
      screen.queryByRole("button", { name: "Перейти к оплате" }),
    ).toBeNull();
  });

  it("пока ссылка создаётся, кнопка заблокирована и подписана", async () => {
    setLatency(50);
    show("month_1");

    const busy = await screen.findByRole("button", {
      name: "Открываем оплату…",
    });
    expect(busy).toBeDisabled();
    await screen.findByRole("link", { name: "Перейти к оплате" });
  });

  it("ссылка создаётся один раз на открытие экрана, а не на каждый рендер", async () => {
    const client = createMockClient();
    const create = vi.spyOn(client, "createCheckout");
    renderWithProviders(
      <Routes>
        <Route path={PATHS.checkout} element={<Checkout />} />
      </Routes>,
      { client, route: ROUTES.checkout("month_1") },
    );

    await screen.findByRole("link", { name: "Перейти к оплате" });
    expect(create).toHaveBeenCalledOnce();
    expect(create).toHaveBeenCalledWith("month_1");
  });

  it("отказ по лимиту называет причину и не предлагает мгновенный повтор", async () => {
    setFault("rate_limited");
    show("month_1");

    await waitFor(() =>
      expect(
        screen.getByText("Слишком много запросов. Подождите минуту."),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("link", { name: "Перейти к оплате" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
  });

  it("сетевой сбой при создании ссылки даёт повторить, и повтор приводит к ссылке", async () => {
    // Каталог читается до сбоя, поэтому ломаем только создание ссылки.
    const client = createMockClient();
    vi.spyOn(client, "createCheckout").mockRejectedValueOnce(
      new ApiError("network", 0),
    );
    renderWithProviders(
      <Routes>
        <Route path={PATHS.checkout} element={<Checkout />} />
      </Routes>,
      { client, route: ROUTES.checkout("month_1") },
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "Повторить" }),
    );
    expect(
      await screen.findByRole("link", { name: "Перейти к оплате" }),
    ).toBeVisible();
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
