import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getState,
  resetStore,
  setFault,
  setLatency,
  subscribeStore,
} from "./store";

describe("mock/store", () => {
  beforeEach(() => {
    sessionStorage.clear();
    resetStore("active");
  });

  it("сценарий new_user не даёт подписки и оставляет trial доступным", () => {
    resetStore("new_user");
    expect(getState().subscription).toBeNull();
    expect(getState().me.trial_available).toBe(true);
  });

  it("сценарий active даёт подписку и два устройства", () => {
    expect(getState().subscription?.status).toBe("active");
    expect(getState().devices).toHaveLength(2);
  });

  it("сценарий device_limit заполняет лимит целиком", () => {
    resetStore("device_limit");
    const s = getState();
    expect(s.devices).toHaveLength(s.subscription!.device_limit);
  });

  it("сброс не тащит мутации предыдущего сценария", () => {
    getState().devices.pop();
    expect(getState().devices).toHaveLength(1);
    resetStore("active");
    expect(getState().devices).toHaveLength(2);
  });

  it("подписчики вызываются на каждое изменение", () => {
    const spy = vi.fn();
    const unsubscribe = subscribeStore(spy);
    setFault("network");
    setLatency(0);
    expect(spy).toHaveBeenCalledTimes(2);
    unsubscribe();
    setFault("none");
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("выбранный сценарий переживает перезагрузку страницы", () => {
    resetStore("exhausted");
    expect(sessionStorage.getItem("tma.mock.scenario")).toBe("exhausted");
  });

  it("неизвестный сценарий в sessionStorage не роняет приложение", () => {
    sessionStorage.setItem("tma.mock.scenario", "нет-такого");
    expect(() => resetStore()).not.toThrow();
    expect(getState().scenario).toBe("active");
  });
});
