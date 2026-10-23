import { describe, expect, it } from "vitest";
import { backTargetFor, hasTabBar, ROUTES, titleFor } from "./routes";

describe("маршрут «Друзья»", () => {
  it("лежит внутри аккаунта: без таб-бара, с заголовком, назад — в аккаунт", () => {
    expect(ROUTES.friends).toBe("/friends");
    expect(hasTabBar("/friends")).toBe(false);
    expect(titleFor("/friends")).toBe("title.friends");
    expect(backTargetFor("/friends")).toBe(ROUTES.account);
  });
});
