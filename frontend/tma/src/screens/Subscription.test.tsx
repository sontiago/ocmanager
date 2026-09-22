import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/contract";
import { createMockClient } from "../api/mock/client";
import { PLANS } from "../api/mock/fixtures";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import type { Subscription as Sub } from "../api/types";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Subscription } from "./Subscription";

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

/** Безлимитной подписки нет ни в одном сценарии — подменяем один метод. */
function clientWith(subscription: Sub): ApiClient {
  return { ...createMockClient(), getSubscription: async () => subscription };
}

function unlimited(): Sub {
  const plan = PLANS[1]; // «Полгода», traffic_limit_bytes === null
  const now = Date.now();
  return {
    id: "sub_unlimited",
    plan,
    status: "active",
    started_at: new Date(now).toISOString(),
    expires_at: new Date(now + 180 * 86_400_000).toISOString(),
    traffic_used_bytes: 91 * 1024 ** 3,
    traffic_limit_bytes: null,
    traffic_period_start: new Date(now).toISOString(),
    device_limit: 5,
    devices_used: 1,
    auto_renew: true,
  };
}

describe("главный экран", () => {
  it("на время загрузки показывает скелет", () => {
    setLatency(50);
    const { container } = renderWithProviders(<Subscription />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("без подписки предлагает выбрать тариф", async () => {
    resetStore("new_user");
    renderWithProviders(<Subscription />);
    await waitFor(() => expect(screen.getByText("Подписки нет")).toBeVisible());

    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать тариф" }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.plans);
  });

  it("действующая подписка отвечает сроком, тарифом и автопродлением", async () => {
    renderWithProviders(<Subscription />);
    await waitFor(() => expect(screen.getByText("20")).toBeVisible());
    expect(screen.getByText("Доступ активен ещё")).toBeVisible();
    expect(screen.getByText(/Месяц/)).toBeVisible();
    expect(screen.getByText(/Продлевается автоматически/)).toBeVisible();
  });

  it("показывает потраченный трафик и процент", async () => {
    renderWithProviders(<Subscription />);
    await waitFor(() =>
      expect(screen.getByText("34 ГБ из 200 ГБ")).toBeVisible(),
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "17",
    );
  });

  it("безлимит показан словами и без полосы прогресса", async () => {
    renderWithProviders(<Subscription />, { client: clientWith(unlimited()) });
    await waitFor(() =>
      expect(screen.getByText("Без ограничений")).toBeVisible(),
    );
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("cancelled — это действующий доступ, а не отключённая подписка", async () => {
    resetStore("cancelled");
    renderWithProviders(<Subscription />);
    await waitFor(() =>
      expect(screen.getByText(/Автопродление отключено/)).toBeVisible(),
    );
    expect(screen.getByText("Доступ активен ещё")).toBeVisible();
    expect(screen.queryByText("Подписки нет")).toBeNull();
  });

  it("истекающая подписка показывает остаток дней", async () => {
    resetStore("expiring_soon");
    renderWithProviders(<Subscription />);
    await waitFor(() => expect(screen.getByText("2")).toBeVisible());
    expect(screen.getByText("дня")).toBeVisible();
  });

  it("исчерпанный трафик назван словами и показан полной полосой", async () => {
    resetStore("exhausted");
    renderWithProviders(<Subscription />);
    await waitFor(() =>
      expect(screen.getByText("Трафик исчерпан")).toBeVisible(),
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    // Период ещё идёт: даты окончания на экране быть не должно.
    expect(screen.queryByText(/Закончилась/)).toBeNull();
    expect(screen.getByRole("button", { name: "Сменить тариф" })).toBeVisible();
  });

  it("истёкшая подписка предлагает возобновить", async () => {
    resetStore("expired");
    renderWithProviders(<Subscription />);
    await waitFor(() => expect(screen.getByText("Истекла")).toBeVisible());

    await userEvent.click(screen.getByRole("button", { name: "Возобновить" }));
    expect(navigate).toHaveBeenCalledWith(ROUTES.plans);
    // Трафик истёкшей подписки ни о чём не говорит и на экране не нужен.
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("строка устройств называет их и ведёт в список", async () => {
    renderWithProviders(<Subscription />);
    const row = await screen.findByRole("button", { name: /^Устройства/ });
    expect(row).toHaveAccessibleName(/iPhone Ивана/);
    expect(row).toHaveAccessibleName(/2 \/ 3/);

    await userEvent.click(row);
    expect(navigate).toHaveBeenCalledWith(ROUTES.devices);
  });

  it("на выбранном лимите устройств вместо кнопки объяснение", async () => {
    resetStore("device_limit");
    renderWithProviders(<Subscription />);
    await waitFor(() =>
      expect(
        screen.getByText("Достигнут лимит устройств тарифа"),
      ).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Добавить устройство" }),
    ).toBeNull();
  });

  it("ошибка загрузки даёт экран ошибки с повтором", async () => {
    setFault("node_unavailable");
    renderWithProviders(<Subscription />);
    await waitFor(() =>
      expect(
        screen.getByText("Сервер временно недоступен. Попробуйте позже."),
      ).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("строка автопродления называет сумму и ведёт на продление", async () => {
    renderWithProviders(<Subscription />);
    const row = await screen.findByRole("button", { name: /^Автопродление/ });
    expect(row).toHaveAccessibleName(/299/);

    await userEvent.click(row);
    expect(navigate).toHaveBeenCalledWith(ROUTES.renew);
  });
});
