import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";
import { useApiMutation } from "./mutate";

export interface PaymentFilters {
  client_id?: number;
  status?: string;
  since?: string;
  until?: string;
  limit: number;
  offset: number;
}

export function usePayments(filters: PaymentFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.payments.list({ ...filters }),
    queryFn: () => client.get<Page<S<"PaymentOut">>>("/payments", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

export interface WebhookFilters {
  status?: string;
  provider?: string;
  limit: number;
  offset: number;
}

export function useWebhooks(filters: WebhookFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.webhooks.list({ ...filters }),
    queryFn: () => client.get<Page<S<"WebhookOut">>>("/webhooks", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

export function useWebhook(id: number | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.webhooks.detail(id ?? 0),
    queryFn: () => client.get<S<"WebhookDetail">>(`/webhooks/${id}`),
    enabled: id !== null,
  });
}

export const useReprocessWebhook = () =>
  useApiMutation<number, S<"WebhookOut">>(
    (c, id) => c.post(`/webhooks/${id}/reprocess`),
    [queryKeys.webhooks.all, queryKeys.overview],
  );
