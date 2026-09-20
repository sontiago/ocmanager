import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { getState, resetStore, setLatency } from "../api/mock/store";
import { renderWithProviders } from "../test/renderWithProviders";
import { DevPanel } from "./DevPanel";

beforeEach(() => {
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
});

describe("DevPanel", () => {
  it("открывается по кнопке", async () => {
    renderWithProviders(<DevPanel />);
    await userEvent.click(screen.getByRole("button", { name: /сценарий/i }));
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("переключение сценария меняет состояние стора", async () => {
    renderWithProviders(<DevPanel />);
    await userEvent.click(screen.getByRole("button", { name: /сценарий/i }));
    await userEvent.click(
      screen.getByRole("button", { name: /Трафик исчерпан/ }),
    );

    await waitFor(() => expect(getState().scenario).toBe("exhausted"));
    expect(getState().subscription?.status).toBe("exhausted");
  });

  it("переключение сбоя пишется в стор", async () => {
    renderWithProviders(<DevPanel />);
    await userEvent.click(screen.getByRole("button", { name: /сценарий/i }));
    await userEvent.selectOptions(screen.getByLabelText("Сбой"), "network");
    expect(getState().fault).toBe("network");
  });
});
