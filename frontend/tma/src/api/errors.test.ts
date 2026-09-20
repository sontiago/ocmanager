import { describe, expect, it } from "vitest";
import { ApiError, toApiError } from "./errors";

describe("ApiError", () => {
  it("сетевые и серверные ошибки помечены как повторяемые", () => {
    expect(new ApiError("network", 0).retryable).toBe(true);
    expect(new ApiError("internal", 500).retryable).toBe(true);
    expect(new ApiError("node_unavailable", 503).retryable).toBe(true);
  });

  it("ошибки бизнес-правил не повторяются", () => {
    expect(new ApiError("device_limit_reached", 409).retryable).toBe(false);
    expect(new ApiError("trial_already_used", 409).retryable).toBe(false);
    expect(new ApiError("unauthorized", 401).retryable).toBe(false);
  });

  it("каждый код отображается в ключ перевода", () => {
    expect(new ApiError("rate_limited", 429).messageKey()).toBe(
      "error.rate_limited",
    );
  });

  it("toApiError пропускает ApiError без изменений", () => {
    const original = new ApiError("not_found", 404);
    expect(toApiError(original)).toBe(original);
  });

  it("toApiError превращает любую другую ошибку во внутреннюю", () => {
    const converted = toApiError(new TypeError("boom"));
    expect(converted.code).toBe("internal");
    expect(converted.message).toBe("boom");
  });
});
