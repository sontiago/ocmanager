import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IssuedDevice } from "../api/types";
import { ROUTES } from "../app/routes";
import { renderWithProviders } from "../test/renderWithProviders";
import { DeviceSecret } from "./DeviceSecret";
import { clearIssued, peekIssued, stashIssued } from "./secretVault";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useNavigate: () => navigate };
});

const links = vi.hoisted(() => ({
  openExternal: vi.fn(),
  openInTelegram: vi.fn(),
  closeApp: vi.fn(),
}));
vi.mock("../telegram/links", () => links);

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,QR") },
}));

function issued(over: Partial<IssuedDevice> = {}): IssuedDevice {
  const now = Date.now();
  return {
    device: {
      id: "dev_9",
      name: "iPhone",
      platform: "ios",
      issued_at: new Date(now).toISOString(),
      cert_expires_at: new Date(now + 397 * 86_400_000).toISOString(),
      last_seen_at: null,
      is_online: false,
      traffic_used_bytes: 0,
    },
    p12_password: "AbCdEfGhJkLm",
    download_url: "https://app.example.com/download/abc",
    download_expires_at: new Date(now + 15 * 60_000).toISOString(),
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  clearIssued();
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => clearIssued());

describe("экран выдачи ключа", () => {
  it("без секрета уводит в список устройств, а не показывает пустоту", async () => {
    renderWithProviders(<DeviceSecret />);
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(ROUTES.devices, { replace: true }),
    );
  });

  it("показывает пароль и предупреждает, что показ единственный", () => {
    stashIssued(issued());
    renderWithProviders(<DeviceSecret />);

    expect(screen.getByText("AbCdEfGhJkLm")).toBeVisible();
    expect(screen.getByText(/показываются один раз/)).toBeVisible();
  });

  it("пароль копируется в буфер обмена", async () => {
    stashIssued(issued());
    renderWithProviders(<DeviceSecret />);

    await userEvent.click(screen.getByRole("button", { name: "Скопировать" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("AbCdEfGhJkLm");
    await waitFor(() => expect(screen.getByText("Скопировано")).toBeVisible());
  });

  it("рисует QR со ссылкой на скачивание", async () => {
    stashIssued(issued());
    renderWithProviders(<DeviceSecret />);

    await waitFor(() =>
      expect(screen.getByRole("img")).toHaveAttribute(
        "src",
        "data:image/png;base64,QR",
      ),
    );
  });

  it("показывает, сколько осталось жить ссылке", () => {
    stashIssued(
      issued({
        download_expires_at: new Date(Date.now() + 61_000).toISOString(),
      }),
    );
    renderWithProviders(<DeviceSecret />);
    expect(screen.getByText(/01:0[01]/)).toBeVisible();
  });

  it("скачивание уходит во внешний браузер, а не в мини-приложение", async () => {
    stashIssued(issued());
    renderWithProviders(<DeviceSecret />);

    await userEvent.click(screen.getByRole("button", { name: "Скачать ключ" }));
    expect(links.openExternal).toHaveBeenCalledWith(
      "https://app.example.com/download/abc",
    );
  });

  it("истёкшая ссылка объясняет, что делать, и не притворяется рабочей", () => {
    stashIssued(
      issued({
        download_expires_at: new Date(Date.now() - 1000).toISOString(),
      }),
    );
    renderWithProviders(<DeviceSecret />);

    expect(
      screen.getByText("Ссылка истекла. Выпустите новое устройство."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Скачать ключ" })).toBeNull();
  });

  it("секрет не попадает ни в адрес, ни в переходы", () => {
    stashIssued(issued());
    renderWithProviders(<DeviceSecret />);

    expect(window.location.href).not.toContain("AbCdEfGhJkLm");
    for (const call of navigate.mock.calls) {
      expect(JSON.stringify(call)).not.toContain("AbCdEfGhJkLm");
    }
  });

  it("уход с экрана стирает секрет из памяти", () => {
    stashIssued(issued());
    const { unmount } = renderWithProviders(<DeviceSecret />);
    unmount();
    expect(peekIssued()).toBeNull();
  });
});
