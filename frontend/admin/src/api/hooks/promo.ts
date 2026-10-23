import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";
import { useApiMutation } from "./mutate";

export function usePromoCodes() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.promo.all,
    queryFn: () => client.get<S<"PromoOut">[]>("/promo-codes"),
  });
}

export function useRedemptions(id: number | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.promo.redemptions(id ?? 0),
    queryFn: () => client.get<S<"RedemptionOut">[]>(`/promo-codes/${id}/redemptions`),
    enabled: id !== null,
  });
}

export const useCreatePromo = () =>
  useApiMutation<S<"PromoCreate">, S<"PromoOut">>((c, body) => c.post("/promo-codes", body), [
    queryKeys.promo.all,
  ]);

export const useDeletePromo = () =>
  useApiMutation<number, void>((c, id) => c.delete(`/promo-codes/${id}`), [queryKeys.promo.all]);

export const usePatchPromo = () =>
  useApiMutation<{ id: number; patch: S<"PromoPatch"> }, S<"PromoOut">>(
    (c, { id, patch }) => c.patch(`/promo-codes/${id}`, patch),
    [queryKeys.promo.all],
  );
