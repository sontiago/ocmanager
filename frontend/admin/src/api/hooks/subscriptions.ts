import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";
import { useApiMutation } from "./mutate";

export interface SubscriptionFilters {
  status?: string;
  plan?: string;
  expiring_within_days?: number;
  limit: number;
  offset: number;
}

export function useSubscriptions(filters: SubscriptionFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.subscriptions.list({ ...filters }),
    queryFn: () => client.get<Page<S<"SubscriptionRow">>>("/subscriptions", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

const refresh = [queryKeys.subscriptions.all, queryKeys.clients.all, queryKeys.overview] as const;

export const useCancelAutoRenew = () =>
  useApiMutation<number, S<"ActionOut">>(
    (c, clientId) => c.post(`/subscriptions/${clientId}/cancel-auto-renew`),
    refresh,
  );

export const useExpire = () =>
  useApiMutation<number, S<"ActionOut">>(
    (c, clientId) => c.post(`/subscriptions/${clientId}/expire`),
    refresh,
  );
