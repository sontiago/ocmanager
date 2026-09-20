import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const navigate = vi.fn();
const offClick = vi.fn();

const sdk = vi.hoisted(() => ({
  show: vi.fn(),
  hide: vi.fn(),
  onClick: vi.fn(),
  isMounted: vi.fn(() => true),
}));

vi.mock("@telegram-apps/sdk-react", () => ({
  backButton: {
    show: Object.assign(sdk.show, { isAvailable: () => true }),
    hide: Object.assign(sdk.hide, { isAvailable: () => true }),
    onClick: Object.assign(sdk.onClick, { isAvailable: () => true }),
    isMounted: sdk.isMounted,
  },
}));

vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return { ...actual, useNavigate: () => navigate };
});

const { useBackButton } = await import("./backButton");

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

beforeEach(() => {
  vi.clearAllMocks();
  sdk.onClick.mockReturnValue(offClick);
});

describe("useBackButton", () => {
  it("показывает кнопку, когда цель задана", () => {
    renderHook(() => useBackButton("/devices"), { wrapper });
    expect(sdk.show).toHaveBeenCalled();
    expect(sdk.hide).not.toHaveBeenCalled();
  });

  it("прячет кнопку на корневом экране", () => {
    renderHook(() => useBackButton(null), { wrapper });
    expect(sdk.hide).toHaveBeenCalled();
    expect(sdk.show).not.toHaveBeenCalled();
  });

  it("клик ведёт на указанный путь, а не в историю браузера", () => {
    renderHook(() => useBackButton("/devices"), { wrapper });
    const handler = sdk.onClick.mock.calls[0][0] as () => void;
    handler();
    expect(navigate).toHaveBeenCalledWith("/devices");
  });

  it("отписывается при размонтировании — иначе обработчики копятся", () => {
    const { unmount } = renderHook(() => useBackButton("/devices"), {
      wrapper,
    });
    unmount();
    expect(offClick).toHaveBeenCalled();
    expect(sdk.hide).toHaveBeenCalled();
  });
});
