import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { ApiProvider } from "./ApiProvider";
import { createQueryClient } from "./queryClient";
import {
  useCreateDevice,
  useDevices,
  useRevokeDevice,
  useSubscription,
} from "./hooks";
import { createMockClient } from "./mock/client";
import { resetStore, setFault, setLatency } from "./mock/store";

function wrapper({ children }: { children: ReactNode }) {
  const qc = createQueryClient();
  qc.setDefaultOptions({ queries: { retry: false, gcTime: 0 } });
  return (
    <QueryClientProvider client={qc}>
      <ApiProvider client={createMockClient()}>{children}</ApiProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
  setFault("none");
});

describe("хуки данных", () => {
  it("useDevices загружает список", async () => {
    const { result } = renderHook(() => useDevices(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });

  it("выпуск устройства инвалидирует и устройства, и подписку", async () => {
    const { result } = renderHook(
      () => ({
        devices: useDevices(),
        subscription: useSubscription(),
        create: useCreateDevice(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.devices.isSuccess).toBe(true));
    await result.current.create.mutateAsync({
      name: "Планшет",
      platform: "android",
    });

    await waitFor(() => expect(result.current.devices.data).toHaveLength(3));
    await waitFor(() =>
      expect(result.current.subscription.data?.devices_used).toBe(3),
    );
  });

  it("отзыв устройства убирает его из кэша", async () => {
    const { result } = renderHook(
      () => ({ devices: useDevices(), revoke: useRevokeDevice() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.devices.isSuccess).toBe(true));
    const victim = result.current.devices.data![0].id;
    await result.current.revoke.mutateAsync(victim);

    await waitFor(() =>
      expect(result.current.devices.data?.some((d) => d.id === victim)).toBe(
        false,
      ),
    );
  });

  it("ошибка бизнес-правила не ретраится", async () => {
    resetStore("device_limit");
    const { result } = renderHook(() => useCreateDevice(), { wrapper });
    await expect(
      result.current.mutateAsync({ name: "Лишнее", platform: "ios" }),
    ).rejects.toMatchObject({ code: "device_limit_reached" });
  });
});
