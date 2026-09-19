import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { I18nProvider } from "./I18nProvider";
import { en } from "./en";
import { ru } from "./ru";
import { useTranslation } from "./useTranslation";

function Probe({
  read,
}: {
  read: (api: ReturnType<typeof useTranslation>) => string;
}) {
  return <span data-testid="out">{read(useTranslation())}</span>;
}

function show(node: ReactNode, lang: "ru" | "en" = "ru") {
  // Каждый вызов show рендерит заново; без очистки в DOM копятся
  // несколько data-testid="out", и getByTestId падает на неоднозначности.
  cleanup();
  render(<I18nProvider lang={lang}>{node}</I18nProvider>);
  return screen.getByTestId("out").textContent;
}

describe("i18n", () => {
  it("английский каталог покрывает русский целиком", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
  });

  it("ни одно значение не пустое", () => {
    for (const [key, value] of Object.entries({ ...ru, ...en })) {
      expect(value, `пустой перевод: ${key}`).not.toBe("");
    }
  });

  it("отдаёт строку по ключу", () => {
    expect(show(<Probe read={({ t }) => t("plans.title")} />)).toBe("Тарифы");
  });

  it("переключает язык", () => {
    expect(show(<Probe read={({ t }) => t("plans.title")} />, "en")).toBe(
      "Plans",
    );
  });

  it("подставляет параметры", () => {
    expect(
      show(
        <Probe
          read={({ t }) => t("subscription.expiresOn", { date: "5 мая" })}
        />,
      ),
    ).toBe("Действует до 5 мая");
  });

  it("оставляет плейсхолдер, если параметр не передан", () => {
    expect(show(<Probe read={({ t }) => t("subscription.expiresOn")} />)).toBe(
      "Действует до {date}",
    );
  });

  it("русские множественные: 1 / 2 / 5 / 21", () => {
    const day = (n: number) => (
      <Probe read={({ tPlural }) => tPlural("unit.day", n)} />
    );
    expect(show(day(1))).toBe("1 день");
    expect(show(day(2))).toBe("2 дня");
    expect(show(day(5))).toBe("5 дней");
    expect(show(day(21))).toBe("21 день");
  });

  it("английские множественные: 1 / 3", () => {
    const dev = (n: number) => (
      <Probe read={({ tPlural }) => tPlural("unit.device", n)} />
    );
    expect(show(dev(1), "en")).toBe("1 device");
    expect(show(dev(3), "en")).toBe("3 devices");
  });
});
