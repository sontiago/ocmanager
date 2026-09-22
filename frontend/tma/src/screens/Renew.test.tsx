import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Renew } from "./Renew";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useNavigate: () => navigate };
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
  setFault("none");
});

describe("экран продления", () => {
  it("на время загрузки показывает скелет", () => {
    setLatency(50);
    const { container } = renderWithProviders(<Renew />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("называет сумму следующего списания и провайдера", async () => {
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText(/299/)).toBeVisible());
    expect(screen.getByText("Следующее списание")).toBeVisible();
    // Именно строка под суммой: «21 сентября 2026 г. · Tribute».
    expect(screen.getByText(/· Tribute$/)).toBeVisible();
  });

  it("показывает тариф, период и состояние автопродления", async () => {
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText("Месяц")).toBeVisible());
    expect(screen.getByText("30 дней")).toBeVisible();
    expect(screen.getByText("включено")).toBeVisible();
  });

  it("автопродление — факт, а не кнопка: переключить его здесь нельзя", async () => {
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText("включено")).toBeVisible());

    // Единственная кнопка экрана — продление; строки карточки некликабельны.
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveAccessibleName(/Продлить сейчас/);
    expect(
      screen.getByText(/Включается и отключается в Tribute/),
    ).toBeVisible();
  });

  it("продление уводит на экран оплаты текущего тарифа", async () => {
    renderWithProviders(<Renew />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Продлить сейчас на 30 дней" }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.checkout("month_1"));
  });

  it("при выключенном автопродлении говорит, когда закончится доступ", async () => {
    resetStore("cancelled");
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText("выключено")).toBeVisible());
    expect(screen.getByText("Стоимость продления")).toBeVisible();
    expect(screen.getByText(/Доступ заканчивается/)).toBeVisible();
  });

  it("истёкшую подписку продлевать нечем — зовёт возобновить", async () => {
    resetStore("expired");
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText("Истекла")).toBeVisible());

    await userEvent.click(screen.getByRole("button", { name: "Возобновить" }));
    expect(navigate).toHaveBeenCalledWith(ROUTES.plans);
  });

  it("без подписки зовёт выбрать тариф", async () => {
    resetStore("new_user");
    renderWithProviders(<Renew />);
    await waitFor(() => expect(screen.getByText("Подписки нет")).toBeVisible());
    expect(screen.getByRole("button", { name: "Выбрать тариф" })).toBeVisible();
  });

  it("ошибка загрузки даёт экран ошибки с повтором", async () => {
    setFault("network");
    renderWithProviders(<Renew />);
    await waitFor(() =>
      expect(screen.getByText("Что-то пошло не так")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
