import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";

const STALE_MS = 60_000;

export function useTrafficStats(days: number) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.stats.traffic(days),
    queryFn: () => client.get<S<"TrafficStats">>("/stats/traffic", { days }),
    staleTime: STALE_MS,
  });
}

export function useRevenueStats(days: number) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.stats.revenue(days),
    queryFn: () => client.get<S<"RevenueStats">>("/stats/revenue", { days }),
    staleTime: STALE_MS,
  });
}

export function useClientsStats(days: number) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.stats.clients(days),
    queryFn: () => client.get<S<"ClientsStats">>("/stats/clients", { days }),
    staleTime: STALE_MS,
  });
}

export function useEconomics() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.stats.economics,
    queryFn: () => client.get<S<"EconomicsStats">>("/stats/economics"),
    staleTime: STALE_MS,
  });
}
