import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatCountdown,
  formatDate,
  formatMoney,
  formatRelative,
} from "./format";

/** Intl вставляет неразрывные пробелы — для читаемости утверждений нормализуем. */
const norm = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

describe("formatBytes", () => {
  it("ноль", () => {
    expect(norm(formatBytes(0, "ru"))).toBe("0 Б");
  });

  it("килобайты, мегабайты, гигабайты, терабайты", () => {
    expect(norm(formatBytes(2048, "ru"))).toBe("2 КБ");
    expect(norm(formatBytes(5 * 1024 ** 2, "ru"))).toBe("5 МБ");
    expect(norm(formatBytes(1024 ** 3, "ru"))).toBe("1 ГБ");
    expect(norm(formatBytes(3 * 1024 ** 4, "ru"))).toBe("3 ТБ");
  });

  it("дробная часть — один знак и только когда нужна", () => {
    expect(norm(formatBytes(1.5 * 1024 ** 3, "ru"))).toBe("1,5 ГБ");
    expect(norm(formatBytes(1.04 * 1024 ** 3, "ru"))).toBe("1 ГБ");
  });

  it("английские единицы", () => {
    expect(norm(formatBytes(1024 ** 3, "en"))).toBe("1 GB");
  });

  it("отрицательные и NaN не показываются пользователю как мусор", () => {
    expect(norm(formatBytes(-5, "ru"))).toBe("0 Б");
    expect(norm(formatBytes(Number.NaN, "ru"))).toBe("0 Б");
  });
});

describe("formatMoney", () => {
  it("минорные единицы превращаются в рубли", () => {
    expect(norm(formatMoney(29900, "RUB", "ru"))).toBe("299 ₽");
  });

  it("копейки показываются, когда они есть", () => {
    expect(norm(formatMoney(29950, "RUB", "ru"))).toBe("299,50 ₽");
  });

  it("доллары в английской локали", () => {
    expect(norm(formatMoney(999, "USD", "en"))).toBe("$9.99");
  });

  it("Telegram Stars — не ISO-валюта, Intl её не знает", () => {
    expect(formatMoney(150, "XTR", "ru")).toBe("150 ⭐");
  });

  it("неизвестная валюта не роняет приложение", () => {
    expect(norm(formatMoney(100, "ZZZ", "ru"))).toContain("1");
  });
});

describe("formatDate", () => {
  it("русская дата", () => {
    expect(norm(formatDate("2026-05-05T10:00:00Z", "ru"))).toBe(
      "5 мая 2026 г.",
    );
  });

  it("английская дата", () => {
    expect(norm(formatDate("2026-05-05T10:00:00Z", "en"))).toBe("May 5, 2026");
  });

  it("битая дата не роняет рендер", () => {
    expect(formatDate("не-дата", "ru")).toBe("—");
  });
});

describe("formatCountdown", () => {
  it("минуты и секунды", () => {
    expect(formatCountdown(14 * 60_000 + 59_000)).toBe("14:59");
  });

  it("дополняет секунды нулём", () => {
    expect(formatCountdown(60_000 + 5_000)).toBe("01:05");
  });

  it("истёкшее время — нули, а не отрицательные значения", () => {
    expect(formatCountdown(-1)).toBe("00:00");
  });
});

describe("formatRelative", () => {
  const now = Date.parse("2026-09-22T12:00:00Z");

  it("часы назад", () => {
    expect(formatRelative("2026-09-22T10:00:00Z", "ru", now)).toMatch(/2 час/);
  });

  it("вчерашнее время называет словом, а не числом", () => {
    expect(formatRelative("2026-09-21T12:00:00Z", "ru", now)).toBe("вчера");
  });

  it("старше месяца показывает датой", () => {
    const old = "2026-01-05T12:00:00Z";
    expect(formatRelative(old, "ru", now)).toBe(formatDate(old, "ru"));
  });

  it("на мусоре не падает", () => {
    expect(formatRelative("не дата", "ru", now)).toBe("—");
  });
});
