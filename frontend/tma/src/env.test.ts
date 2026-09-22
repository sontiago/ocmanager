import { describe, expect, it } from "vitest";
import { readEnv } from "./env";

describe("readEnv", () => {
  it("по умолчанию работает на моках", () => {
    expect(readEnv({}).apiMode).toBe("mock");
  });

  it("читает http-режим", () => {
    expect(readEnv({ VITE_API_MODE: "http" }).apiMode).toBe("http");
  });

  it("падает на неизвестном режиме, а не молча берёт дефолт", () => {
    expect(() => readEnv({ VITE_API_MODE: "grpc" })).toThrow(/VITE_API_MODE/);
  });

  it("база API по умолчанию — /api", () => {
    expect(readEnv({}).apiBaseUrl).toBe("/api");
  });

  it("срезает хвостовой слэш у базы API", () => {
    expect(
      readEnv({ VITE_API_BASE_URL: "https://x.dev/api/" }).apiBaseUrl,
    ).toBe("https://x.dev/api");
  });

  it("dev-панель выключена, если флаг не выставлен", () => {
    expect(readEnv({}).devPanel).toBe(false);
  });
  it("контакт поддержки берётся из окружения, иначе остаётся дефолтный", () => {
    expect(readEnv({}).supportHandle).toBe("@ocmanager_help");
    expect(readEnv({ VITE_SUPPORT_HANDLE: "@vpn_help" }).supportHandle).toBe(
      "@vpn_help",
    );
  });
});
