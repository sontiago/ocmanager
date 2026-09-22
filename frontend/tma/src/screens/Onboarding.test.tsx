import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Onboarding } from "./Onboarding";

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

describe("онбординг", () => {
  it("рассказывает, что произойдёт, тремя шагами", async () => {
    renderWithProviders(<Onboarding />);
    expect(screen.getByText("за две минуты")).toBeVisible();
    expect(screen.getByText("Выберите тариф")).toBeVisible();
    expect(screen.getByText("Оплатите в Tribute")).toBeVisible();
    expect(await screen.findByText("Получите ключ")).toBeVisible();
  });

  it("называет условия пробного периода", async () => {
    renderWithProviders(<Onboarding />);
    await waitFor(() => expect(screen.getByText(/3 дня и 5 ГБ/)).toBeVisible());
  });

  it("активация пробного периода уводит на главный экран", async () => {
    renderWithProviders(<Onboarding />);
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Активировать пробный период",
      }),
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(ROUTES.home));
  });

  it("сбой активации называет причину и оставляет на месте", async () => {
    renderWithProviders(<Onboarding />);
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

  it("каталог тарифов доступен сразу, без пробного периода", async () => {
    renderWithProviders(<Onboarding />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Выбрать тариф" }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.plans);
  });

  it("израсходованный пробный период не предлагается", async () => {
    resetStore("trial_used");
    renderWithProviders(<Onboarding />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Выбрать тариф" }),
      ).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Активировать пробный период" }),
    ).toBeNull();
  });

  it("тому, у кого подписка уже есть, рассказывать нечего", async () => {
    resetStore("active");
    renderWithProviders(<Onboarding />);
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(ROUTES.home, { replace: true }),
    );
  });
});
