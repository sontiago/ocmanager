import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "../session";
import { queryKeys } from "../queryKeys";
import type { S } from "../types";

export function useOverview() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: () => client.get<S<"OverviewOut">>("/overview"),
    refetchInterval: 15_000,
  });
}
