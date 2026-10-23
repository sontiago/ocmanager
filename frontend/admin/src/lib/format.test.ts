import { formatBytes, formatDateTime, formatDuration, formatMoney } from "./format";

test("formatBytes_zero", () => {
  expect(formatBytes(0)).toBe("0 Б");
});

test("formatBytes_kilobytes", () => {
  expect(formatBytes(1536)).toMatch(/^1[.,]5 КБ$/);
});

test("formatBytes_gigabytes_rounds_large_values", () => {
  expect(formatBytes(412 * 1024 ** 3)).toBe("412 ГБ");
});

test("formatMoney_divides_minor_units", () => {
  expect(formatMoney(129900, "RUB").replace(/\s/g, "")).toContain("1299");
});

test("formatMoney_unknown_currency_does_not_throw", () => {
  expect(formatMoney(500, "??")).toContain("5");
});

test("formatDateTime_null_is_dash", () => {
  expect(formatDateTime(null)).toBe("—");
});

test("formatDuration_hours_and_minutes", () => {
  expect(formatDuration(3900)).toBe("1ч 5м");
});
