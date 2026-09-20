import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { renderWithProviders } from "../test/renderWithProviders";
import { Button } from "./Button";
import { Cell } from "./Cell";
import { ErrorState } from "./ErrorState";
import { ProgressBar } from "./ProgressBar";
import { Sheet } from "./Sheet";

describe("Button", () => {
  it("вызывает обработчик по клику", async () => {
    const onClick = vi.fn();
    renderWithProviders(<Button onClick={onClick}>Купить</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Купить" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("в состоянии loading заблокирована и помечена для скринридера", () => {
    renderWithProviders(
      <Button loading onClick={vi.fn()}>
        Купить
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("disabled не пропускает клики", async () => {
    const onClick = vi.fn();
    renderWithProviders(
      <Button disabled onClick={onClick}>
        Купить
      </Button>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Cell", () => {
  it("кликабельная ячейка — это кнопка, а не div с обработчиком", async () => {
    const onClick = vi.fn();
    renderWithProviders(
      <Cell title="iPhone" subtitle="онлайн" onClick={onClick} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /iPhone/ }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("некликабельная ячейка кнопкой не притворяется", () => {
    renderWithProviders(<Cell title="Трафик" subtitle="12 ГБ" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ProgressBar", () => {
  it("сообщает значение через ARIA", () => {
    renderWithProviders(<ProgressBar percent={42} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("зажимает выход за границы", () => {
    renderWithProviders(<ProgressBar percent={140} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
  });
});

describe("ErrorState", () => {
  it("показывает переведённое сообщение по коду ошибки", () => {
    renderWithProviders(
      <ErrorState error={new ApiError("rate_limited", 429)} />,
    );
    expect(
      screen.getByText("Слишком много запросов. Подождите минуту."),
    ).toBeVisible();
  });

  it("кнопка повтора появляется только для повторяемых ошибок", () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <ErrorState
        error={new ApiError("device_limit_reached", 409)}
        onRetry={onRetry}
      />,
    );
    expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
  });

  it("повторяемая ошибка даёт кнопку и вызывает обработчик", async () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <ErrorState error={new ApiError("network", 0)} onRetry={onRetry} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("Sheet", () => {
  it("закрытый лист не рендерится", () => {
    renderWithProviders(
      <Sheet open={false} onClose={vi.fn()} title="Отозвать?">
        тело
      </Sheet>,
    );
    expect(screen.queryByText("тело")).toBeNull();
  });

  it("Escape закрывает лист", async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <Sheet open onClose={onClose} title="Отозвать?">
        тело
      </Sheet>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("открытый лист — модальный диалог", () => {
    renderWithProviders(
      <Sheet open onClose={vi.fn()} title="Отозвать?">
        тело
      </Sheet>,
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  });
});
