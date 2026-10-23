import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";
import { useApiMutation } from "./mutate";

export interface ClientFilters {
  q?: string;
  status?: string;
  blocked?: boolean;
  limit: number;
  offset: number;
}

export function useClients(filters: ClientFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.clients.list({ ...filters }),
    queryFn: () => client.get<Page<S<"ClientRow">>>("/clients", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

export function useClient(id: number) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.clients.detail(id),
    queryFn: () => client.get<S<"ClientCard">>(`/clients/${id}`),
  });
}

const refresh = [queryKeys.clients.all, queryKeys.overview, queryKeys.subscriptions.all] as const;

export const useBlockClient = (id: number) =>
  useApiMutation<void, S<"ActionOut">>((c) => c.post(`/clients/${id}/block`), refresh);

export const useUnblockClient = (id: number) =>
  useApiMutation<void, S<"ActionOut">>((c) => c.post(`/clients/${id}/unblock`), refresh);

export const useResetTraffic = (id: number) =>
  useApiMutation<void, S<"ActionOut">>((c) => c.post(`/clients/${id}/reset-traffic`), refresh);

export const useGrant = (id: number) =>
  useApiMutation<{ plan_code: string; days?: number }, S<"ActionOut">>(
    (c, body) => c.post(`/clients/${id}/grant`, body),
    refresh,
  );

export const useExtend = (id: number) =>
  useApiMutation<{ days: number }, S<"ActionOut">>(
    (c, body) => c.post(`/clients/${id}/extend`, body),
    refresh,
  );

/** gcTime 0: пароль .p12 не должен оставаться в кэше мутаций после закрытия диалога. */
export const useIssueDevice = (id: number) =>
  useApiMutation<S<"IssueBody">, S<"IssuedOut">>(
    (c, body) => c.post(`/clients/${id}/devices`, body),
    [queryKeys.clients.all, queryKeys.devices.all],
    { gcTime: 0 },
  );
