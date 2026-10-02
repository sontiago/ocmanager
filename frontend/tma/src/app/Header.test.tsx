import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Header } from "./Header";

describe("Header", () => {
  it("без onBack кнопки «Назад» нет", () => {
    render(<Header title="Тарифы" />);
    expect(screen.getByRole("heading", { name: "Тарифы" })).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("с onBack рисует кнопку «Назад», и она ведёт назад", async () => {
    const onBack = vi.fn();
    render(<Header title="Оплата" onBack={onBack} backLabel="Назад" />);

    await userEvent.click(screen.getByRole("button", { name: "Назад" }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});
