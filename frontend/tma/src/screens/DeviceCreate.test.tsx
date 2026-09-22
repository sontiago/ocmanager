import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { DeviceCreate } from "./DeviceCreate";
import { clearIssued, peekIssued } from "./secretVault";

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
  clearIssued();
});

afterEach(() => clearIssued());

describe("экран выпуска устройства", () => {
  it("предлагает все пять платформ", async () => {
    renderWithProviders(<DeviceCreate />);
    for (const label of ["iOS", "Android", "Windows", "macOS", "Linux"]) {
      expect(
        await screen.findByRole("radio", { name: new RegExp(label) }),
      ).toBeVisible();
    }
  });

  it("не даёт выпустить ключ, пока не выбрана система", async () => {
    renderWithProviders(<DeviceCreate />);
    expect(
      await screen.findByRole("button", { name: "Выпустить ключ" }),
    ).toBeDisabled();
  });

  it("после выбора системы подставляет имя", async () => {
    renderWithProviders(<DeviceCreate />);
    await userEvent.click(await screen.findByRole("radio", { name: /iOS/ }));
    expect(screen.getByLabelText("Название")).toHaveValue("iOS");
  });

  it("пустое имя не даёт выпустить ключ", async () => {
    renderWithProviders(<DeviceCreate />);
    await userEvent.click(await screen.findByRole("radio", { name: /iOS/ }));
    await userEvent.clear(screen.getByLabelText("Название"));
    expect(
      screen.getByRole("button", { name: "Выпустить ключ" }),
    ).toBeDisabled();
  });

  it("выпуск кладёт секрет в память и уводит на экран ключа", async () => {
    renderWithProviders(<DeviceCreate />);
    await userEvent.click(
      await screen.findByRole("radio", { name: /Android/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Выпустить ключ" }),
    );

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(ROUTES.deviceKey("android"), {
        replace: true,
      }),
    );
    expect(peekIssued()?.p12_password).toMatch(/^[A-Za-z0-9]{12}$/);
  });

  it("на выбранном лимите объясняет, а не показывает форму", async () => {
    resetStore("device_limit");
    renderWithProviders(<DeviceCreate />);
    await waitFor(() =>
      expect(
        screen.getByText("Достигнут лимит устройств тарифа"),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("button", { name: "Выпустить ключ" })).toBeNull();
  });

  it("сбой выпуска называет причину и не уводит с экрана", async () => {
    renderWithProviders(<DeviceCreate />);
    await userEvent.click(await screen.findByRole("radio", { name: /iOS/ }));

    setFault("node_unavailable");
    await userEvent.click(
      screen.getByRole("button", { name: "Выпустить ключ" }),
    );

    await waitFor(() =>
      expect(
        screen.getByText("Сервер временно недоступен. Попробуйте позже."),
      ).toBeVisible(),
    );
    expect(navigate).not.toHaveBeenCalled();
    expect(peekIssued()).toBeNull();
  });
});
