import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { resetStore, setLatency } from "../api/mock/store";
import { renderWithProviders } from "../test/renderWithProviders";
import { AppRoutes } from "./router";
import { ROUTES } from "./routes";

beforeEach(() => {
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
});

/** Активная вкладка — единственный признак маршрута, не зависящий от экранов. */
async function activeTab(): Promise<string | null> {
  const active = await waitFor(() => {
    const found = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("aria-current") === "page");
    if (!found) throw new Error("нет активной вкладки");
    return found;
  });
  return active.textContent;
}

describe("маршруты", () => {
  it("корень открывает вкладку подписки", async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.home });
    expect(await activeTab()).toContain("Подписка");
  });

  it("таб-бар ведёт на тарифы", async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.home });
    await userEvent.click(await screen.findByRole("link", { name: /Тарифы/ }));
    expect(await activeTab()).toContain("Тарифы");
  });

  it("неизвестный путь уводит на корень, а не показывает пустоту", async () => {
    renderWithProviders(<AppRoutes />, { route: "/чего-то-нет" });
    expect(await activeTab()).toContain("Подписка");
  });

  it("вложенный экран не показывает таб-бар", async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.deviceNew });
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Новое устройство" }),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("link", { name: /Тарифы/ })).toBeNull();
  });
});
