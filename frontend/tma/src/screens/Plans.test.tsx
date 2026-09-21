import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Plans } from "./Plans";

// Экран рендерится в одиночку, без <Routes>, поэтому переход наблюдаем
// через подменённый useNavigate: проверяем намерение экрана, а не работу
// роутера — она уже проверена в app/router.test.tsx.
const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useNavigate: () => navigate };
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetStore("new_user");
  setLatency(0);
  setFault("none");
});

describe("экран тарифов", () => {
  it("на время загрузки показывает скелет, а не пустоту", () => {
    setLatency(50);
    const { container } = renderWithProviders(<Plans />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("выводит каталог с сроком, лимитом устройств и ценой", async () => {
    renderWithProviders(<Plans />);
    const month = await screen.findByRole("button", { name: /Месяц/ });
    expect(month).toHaveAccessibleName(/30 дней/);
    expect(month).toHaveAccessibleName(/3 устройства/);
    expect(month).toHaveAccessibleName(/299/);
    expect(screen.getByRole("button", { name: /Полгода/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Год/ })).toBeVisible();
  });

  it("безлимитный тариф подписан словами, а не «null ГБ»", async () => {
    renderWithProviders(<Plans />);
    await waitFor(() =>
      expect(screen.getAllByText(/Безлимитный трафик/)).toHaveLength(2),
    );
  });

  it("нажатие на тариф ведёт на экран оплаты", async () => {
    resetStore("trial_used");
    renderWithProviders(<Plans />);
    await userEvent.click(await screen.findByRole("button", { name: /Месяц/ }));
    expect(navigate).toHaveBeenCalledWith(ROUTES.checkout("month_1"));
  });

  it("текущий тариф помечен и ведёт на продление, а не на повторную покупку", async () => {
    resetStore("active");
    renderWithProviders(<Plans />);
    const current = await screen.findByRole("button", { name: /ТЕКУЩИЙ/ });
    await userEvent.click(current);
    expect(navigate).toHaveBeenCalledWith(ROUTES.renew);
  });

  it("новому клиенту предлагает пробный период", async () => {
    renderWithProviders(<Plans />);
    expect(
      await screen.findByRole("button", {
        name: "Активировать пробный период",
      }),
    ).toBeVisible();
    expect(screen.getByText(/3 дня и 5 ГБ/)).toBeVisible();
  });

  it("активация пробного периода уводит на главный экран", async () => {
    renderWithProviders(<Plans />);
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Активировать пробный период",
      }),
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(ROUTES.home));
  });

  it("израсходованный trial показан как использованный и не кликается", async () => {
    resetStore("trial_used");
    renderWithProviders(<Plans />);
    await waitFor(() =>
      expect(screen.getByText("Пробный период уже использован")).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Активировать пробный период" }),
    ).toBeNull();
  });

  it("при действующей подписке пробный период не предлагается вовсе", async () => {
    resetStore("active");
    renderWithProviders(<Plans />);
    await screen.findByRole("button", { name: /Месяц/ });
    expect(screen.queryByText(/Попробовать бесплатно/)).toBeNull();
  });

  it("сбой активации называет причину, а не молчит", async () => {
    renderWithProviders(<Plans />);
    const start = await screen.findByRole("button", {
      name: "Активировать пробный период",
    });
    setFault("internal");
    await userEvent.click(start);

    await waitFor(() =>
      expect(screen.getByText("Внутренняя ошибка сервера.")).toBeVisible(),
    );
    expect(navigate).not.toHaveBeenCalled();
  });

  it("ошибка загрузки каталога даёт экран ошибки с повтором", async () => {
    setFault("network");
    renderWithProviders(<Plans />);
    await waitFor(() =>
      expect(screen.getByText("Что-то пошло не так")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("повтор чинит весь экран, а не один каталог", async () => {
    resetStore("active");
    setFault("network");
    renderWithProviders(<Plans />);

    const retry = await screen.findByRole("button", { name: "Повторить" });
    setFault("none");
    await userEvent.click(retry);

    // Пометка «ТЕКУЩИЙ» держится на /subscription, а её отсутствие —
    // ровно тот симптом, который давал частичный повтор.
    expect(
      await screen.findByRole("button", { name: /ТЕКУЩИЙ/ }),
    ).toBeVisible();
    expect(screen.queryByText("Пробный период уже использован")).toBeNull();
  });
});
