import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";
import { useApiMutation } from "./mutate";

export interface DeviceFilters {
  q?: string;
  platform?: string;
  revoked?: boolean;
  online?: boolean;
  limit: number;
  offset: number;
}

export function useDevices(filters: DeviceFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.devices.list({ ...filters }),
    queryFn: () => client.get<Page<S<"DeviceRow">>>("/devices", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

export function useDeviceSessions(id: number | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.devices.sessions(id ?? 0),
    queryFn: () => client.get<Page<S<"SessionRowOut">>>(`/devices/${id}/sessions`, { limit: 20 }),
    enabled: id !== null,
  });
}

export const useRevokeDevice = () =>
  useApiMutation<{ id: number; reason: string }, S<"DeviceRow">>(
    (c, { id, reason }) => c.post(`/devices/${id}/revoke`, { reason }),
    [queryKeys.devices.all, queryKeys.clients.all],
  );
