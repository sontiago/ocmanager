import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetStore, setFault, setLatency } from "../api/mock/store";
import { renderWithProviders } from "../test/renderWithProviders";
import { Instructions } from "./Instructions";

const links = vi.hoisted(() => ({
  openExternal: vi.fn(),
  openInTelegram: vi.fn(),
  closeApp: vi.fn(),
}));
vi.mock("../telegram/links", () => links);

// Платформа приходит из адреса; меняем её между тестами через общий объект.
const params = vi.hoisted(() => ({ platform: "ios" as string | undefined }));
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useParams: () => ({ platform: params.platform }) };
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
  setFault("none");
  params.platform = "ios";
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("экран инструкций", () => {
  it("на время загрузки показывает скелет", () => {
    setLatency(50);
    const { container } = renderWithProviders(<Instructions />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("показывает шаги выбранной системы", async () => {
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(
        screen.getByText("Установите Cisco Secure Client из App Store"),
      ).toBeVisible(),
    );
    expect(screen.getByText("iOS · Как подключиться")).toBeVisible();
    expect(screen.getByText("04")).toBeVisible();
  });

  it("под другую систему показывает другие шаги", async () => {
    params.platform = "linux";
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(screen.getByText(/apt install openconnect/)).toBeVisible(),
    );
    expect(
      screen.queryByText("Установите Cisco Secure Client из App Store"),
    ).toBeNull();
  });

  it("показывает адрес шлюза и даёт его скопировать", async () => {
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(
        screen.getByText("https://vpn.example.com/f4a91c7b"),
      ).toBeVisible(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Скопировать" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "https://vpn.example.com/f4a91c7b",
    );
    await waitFor(() => expect(screen.getByText("Скопировано")).toBeVisible());
  });

  it("ссылка на клиент открывается снаружи мини-приложения", async () => {
    renderWithProviders(<Instructions />);
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Открыть в магазине приложений",
      }),
    );
    expect(links.openExternal).toHaveBeenCalledOnce();
    expect(links.openExternal.mock.calls[0][0]).toContain("apps.apple.com");
  });

  it("там, где магазина нет, кнопки тоже нет", async () => {
    params.platform = "linux";
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(screen.getByText(/apt install openconnect/)).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Открыть в магазине приложений" }),
    ).toBeNull();
  });

  it("неизвестная система не даёт сломанный экран", async () => {
    params.platform = "symbian";
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(screen.queryByText(/Как подключиться/)).toBeNull(),
    );
  });

  it("сбой загрузки адреса даёт экран ошибки с повтором", async () => {
    setFault("network");
    renderWithProviders(<Instructions />);
    await waitFor(() =>
      expect(screen.getByText("Что-то пошло не так")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
