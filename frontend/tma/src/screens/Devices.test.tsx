import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/contract";
import { createMockClient } from "../api/mock/client";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { Devices } from "./Devices";

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

/** Живая подписка без выпущенных ключей — такого сценария в моке нет. */
function clientWithoutDevices(): ApiClient {
  return { ...createMockClient(), listDevices: async () => [] };
}

/** Открывает лист действий первого устройства. */
async function openActions(name: RegExp) {
  await userEvent.click(await screen.findByRole("button", { name }));
  return within(screen.getByRole("dialog"));
}

describe("экран устройств", () => {
  it("на время загрузки показывает скелет", () => {
    setLatency(50);
    const { container } = renderWithProviders(<Devices />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("с живой подпиской и без ключей зовёт выпустить первый", async () => {
    renderWithProviders(<Devices />, { client: clientWithoutDevices() });
    await waitFor(() =>
      expect(screen.getByText("Устройств пока нет")).toBeVisible(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить устройство" }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.deviceNew);
  });

  it("без подписки зовёт выбрать тариф, а не выпускать ключ", async () => {
    resetStore("new_user");
    renderWithProviders(<Devices />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Выбрать тариф" }),
      ).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Добавить устройство" }),
    ).toBeNull();
  });

  it("выводит устройства с состоянием и трафиком", async () => {
    renderWithProviders(<Devices />);
    await waitFor(() => expect(screen.getByText("iPhone Ивана")).toBeVisible());
    expect(screen.getByText("MacBook")).toBeVisible();
    expect(screen.getByText(/Подключено/)).toBeVisible();
    expect(screen.getByText(/12 ГБ/)).toBeVisible();
    expect(screen.getByText("Занято 2 из 3")).toBeVisible();
  });

  it("устройство без подключений подписано отдельно", async () => {
    resetStore("device_limit");
    renderWithProviders(<Devices />);
    await waitFor(() =>
      expect(screen.getByText(/Ни разу не подключалось/)).toBeVisible(),
    );
  });

  it("свободный слот ведёт на выпуск ключа", async () => {
    renderWithProviders(<Devices />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Свободный слот/ }),
    );
    expect(navigate).toHaveBeenCalledWith(ROUTES.deviceNew);
  });

  it("на выбранном лимите вместо слота — объяснение", async () => {
    resetStore("device_limit");
    renderWithProviders(<Devices />);
    await waitFor(() =>
      expect(
        screen.getByText("Достигнут лимит устройств тарифа"),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("button", { name: /Свободный слот/ })).toBeNull();
  });

  it("устройство открывает лист действий, а не отзывает сразу", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);

    expect(sheet.getByRole("button", { name: /Инструкция/ })).toBeVisible();
    expect(sheet.getByRole("button", { name: "Отозвать" })).toBeVisible();
    expect(screen.getByRole("button", { name: /iPhone Ивана/ })).toBeVisible();
  });

  it("инструкция ведёт на руководство под платформу устройства", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);

    await userEvent.click(sheet.getByRole("button", { name: /Инструкция/ }));
    expect(navigate).toHaveBeenCalledWith(ROUTES.deviceGuide("ios"));
  });

  it("отзыв требует подтверждения и называет устройство", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);
    await userEvent.click(sheet.getByRole("button", { name: "Отозвать" }));

    expect(
      screen.getByText(/«iPhone Ивана» перестанет работать/),
    ).toBeVisible();
  });

  it("отмена подтверждения не трогает устройство", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);
    await userEvent.click(sheet.getByRole("button", { name: "Отозвать" }));
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(
      screen.queryByRole("button", { name: "Отозвать устройство" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: /iPhone Ивана/ })).toBeVisible();
  });

  it("подтверждение убирает устройство из списка", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);
    await userEvent.click(sheet.getByRole("button", { name: "Отозвать" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Отозвать устройство" }),
    );

    await waitFor(() => expect(screen.queryByText("iPhone Ивана")).toBeNull());
    expect(screen.getByText("MacBook")).toBeVisible();
  });

  it("сбой отзыва называет причину, устройство остаётся", async () => {
    renderWithProviders(<Devices />);
    const sheet = await openActions(/iPhone Ивана/);
    await userEvent.click(sheet.getByRole("button", { name: "Отозвать" }));

    setFault("internal");
    await userEvent.click(
      screen.getByRole("button", { name: "Отозвать устройство" }),
    );

    await waitFor(() =>
      expect(screen.getByText("Внутренняя ошибка сервера.")).toBeVisible(),
    );
    expect(screen.getByText("iPhone Ивана")).toBeVisible();
  });

  it("ошибка загрузки даёт экран ошибки с повтором", async () => {
    setFault("network");
    renderWithProviders(<Devices />);
    await waitFor(() =>
      expect(screen.getByText("Что-то пошло не так")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
